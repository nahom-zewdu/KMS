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
from datetime import datetime, timedelta
from typing import Dict, Any

from engine.llm import llm_infer
from supabase import Client
from visualizer.service import VisualizerService

logger = logging.getLogger(__name__)


class PlaybookGenerator:
    """Generates role-specific onboarding playbooks with rich structured data."""

    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.visualizer = VisualizerService(supabase)

    def generate(self, role: str, company_id: str = "default", employee_name: str = None) -> Dict[str, Any]:
        """Main playbook generation."""
        logger.info(f"Generating playbook for role: {role} (company: {company_id})")

        # 1. Get visualizer data
        visualizer_data = self.visualizer.build_for_role(role)

        # 2. Compact context for LLM
        compact_context = self._gather_compact_context(role)

        prompt = f"""
            You are an elite engineering onboarding architect.

            **Role**: {role}
            **New Hire**: {employee_name or "New Engineer"}

            **Real Company Context**:
            {compact_context}

            **Visualizer Summary** (use this structure):
            {json.dumps(visualizer_data, indent=2)[:2600]}

            Create a practical, motivating, and highly actionable onboarding playbook.
            Return **only valid JSON**:

            {{
            "title": "Onboarding Playbook — {role}",
            "welcome_message": "Warm welcome message...",
            "sections": [
                {{"title": "Week 1 Goals", "content": "..."}},
                {{"title": "Key People & Ownership", "content": "..."}},
                {{"title": "Core Systems & Architecture", "content": "..."}},
                {{"title": "Codebase Navigation & Safe Zones", "content": "..."}},
                {{"title": "Learning Path & First Tasks", "content": "..."}}
            ]
            }}
        """

        raw = llm_infer(prompt, temperature=0.3, max_tokens=1800)

        try:
            cleaned = raw.strip()
            if cleaned.startswith("```json"): cleaned = cleaned[7:]
            if cleaned.endswith("```"): cleaned = cleaned[:-3]
            playbook = json.loads(cleaned)
        except Exception as e:
            logger.warning(f"JSON parse failed: {e}. Using fallback.")
            playbook = self._fallback_playbook(role)

        # Always attach full visualizer data (post-LLM)
        playbook["visualizer"] = visualizer_data

        # Save to DB (idempotent)
        record = {
            "company_id": company_id,
            "role": role.lower().replace(" ", "-"),
            "title": playbook.get("title", f"Onboarding Playbook — {role}"),
            "content": playbook,
            "generated_for": employee_name,
            "expires_at": (datetime.utcnow() + timedelta(days=90)).isoformat(),
            "is_active": True
        }

        try:
            # Use upsert with correct constraint
            self.supabase.table("playbooks").upsert(record, on_conflict="company_id,role").execute()
            logger.info(f"Playbook saved for {role}")
        except Exception as e:
            logger.error(f"Failed to save playbook: {e}")

        logger.info(f"Playbook generated successfully for {role}")
        return playbook

    def _gather_compact_context(self, role: str) -> str:
        """Token-efficient context."""
        parts = []

        # People (limited)
        people = self.supabase.table("entities").select("name").eq("type", "PERSON").limit(6).execute()
        if people.data:
            parts.append("Key People: " + ", ".join(p["name"] for p in people.data))

        # Recent activity (very short)
        recent = self.supabase.table("raw_data").select("content").order("created_at", desc=True).limit(4).execute()
        if recent.data:
            parts.append("Recent: " + " | ".join(r["content"][:90] for r in recent.data))

        # Key files (limited)
        files = self.supabase.table("codebase_files").select("file_path").limit(8).execute()
        if files.data:
            parts.append("Key Files: " + ", ".join(f["file_path"] for f in files.data[:5]))

        return "\n".join(parts)

    def _fallback_playbook(self, role: str) -> Dict:
        return {
            "title": f"Onboarding Playbook — {role}",
            "welcome_message": f"Welcome to the team as our new {role}!",
            "sections": []
        }
