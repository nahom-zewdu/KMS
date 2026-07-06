# nlp/playbooks/generator.py
"""
Generates world-class, data-rich onboarding playbooks for new engineers.
Uses real data from:
- Knowledge Graph (entities + relationships)
- Codebase structure (modules + files)
The playbook is generated via LLM inference, with a structured prompt that includes:
- Role-specific context
- Visualizer data (architecture, modules, key files, learning path)
The generated playbook is saved to Supabase for retrieval by the frontend.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from engine.llm import llm_infer
from supabase import Client
from visualizer.service import VisualizerService

logger = logging.getLogger(__name__)

class PlaybookGenerator:
    """Generates world-class, data-rich onboarding playbooks."""

    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.visualizer = VisualizerService(supabase)

    def generate(self, role: str, company_id: str = "default", employee_name: str = None) -> Dict[str, Any]:
        """Generate full playbook with visualizer data embedded."""
        logger.info(f"Generating playbook for role: {role}")

        # 1. Get rich visualizer data
        visualizer_data = self.visualizer.build_for_role(role)

        # 2. Gather additional context
        context = self._gather_rich_context(role)

        # 3. LLM prompt with real data
        prompt = f"""
            You are an elite engineering onboarding architect for a fintech/SaaS company.

            **Role**: {role}
            **Employee**: {employee_name or "New Engineer"}

            **Real Context**:
            {context}

            **Visualizer Data** (use this structure):
            {json.dumps(visualizer_data, indent=2)}

            Create a **highly specific, actionable onboarding playbook**.
            Return **only valid JSON**:

            {{
            "title": "Onboarding Playbook — {role}",
            "welcome_message": "Warm, motivating welcome...",
            "sections": [
                {{"title": "Week 1 Goals", "content": "..."}},
                {{"title": "Key People & Ownership", "content": "..."}},
                {{"title": "Core Systems & Architecture", "content": "..."}},
                {{"title": "Codebase Navigation", "content": "..."}},
                {{"title": "Safe First Contributions", "content": "..."}},
                {{"title": "Learning Path", "content": "..."}}
            ],
            "visualizer": {json.dumps(visualizer_data)}
            }}
        """

        raw = llm_infer(prompt, temperature=0.3, max_tokens=3000)

        try:
            # Clean JSON
            cleaned = raw.strip()
            if cleaned.startswith("```json"): cleaned = cleaned[7:]
            if cleaned.endswith("```"): cleaned = cleaned[:-3]
            playbook = json.loads(cleaned)
        except Exception as e:
            logger.warning(f"JSON parse failed: {e}. Using fallback.")
            playbook = self._fallback_playbook(role, visualizer_data)

        # Save to DB
        record = {
            "company_id": company_id,
            "role": role.lower().replace(" ", "-"),
            "title": playbook.get("title"),
            "content": playbook,
            "generated_for": employee_name,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat(),
            "is_active": True
        }
        try:
            self.supabase.table("playbooks").upsert(record, on_conflict="company_id,role").execute()
        except Exception as e:
            logger.error(f"Failed to save playbook: {e}")

        logger.info(f"✅ Playbook generated successfully for {role}")
        return playbook

    def _gather_rich_context(self, role: str) -> str:
        """Gather real context from KG and recent activity."""
        parts = []

        # People
        people = self.supabase.table("entities").select("name").eq("type", "PERSON").limit(10).execute()
        if people.data:
            parts.append("**Key People:** " + ", ".join(p["name"] for p in people.data))

        # Recent Activity
        recent = self.supabase.table("raw_data").select("content").order("created_at", desc=True).limit(8).execute()
        if recent.data:
            parts.append("**Recent Activity:** " + " | ".join(r["content"][:150] for r in recent.data))

        return "\n\n".join(parts)

    def _fallback_playbook(self, role: str, visualizer_data: Dict) -> Dict:
        """Safe fallback."""
        return {
            "title": f"Onboarding Playbook — {role}",
            "welcome_message": f"Welcome to the team as our new {role}!",
            "sections": [],
            "visualizer": visualizer_data
        }
