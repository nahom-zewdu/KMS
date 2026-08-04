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
    """Generates high-quality, data-rich onboarding playbooks."""

    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.visualizer = VisualizerService(supabase)

    def generate(self, role: str, company_id: str = "default", employee_name: str = None) -> Dict[str, Any]:
        """Main generation entrypoint."""
        logger.info(f"Generating playbook for role: {role}")

        visualizer_data = self.visualizer.build_for_role(role, company_id=company_id)
        compact_context = self._gather_compact_context(role, company_id)

        prompt = f"""
            You are an elite engineering onboarding architect at a fintech/SaaS startup.

            **Role**: {role}
            **New Hire**: {employee_name or "New Engineer"}

            **Real Context**:
            {compact_context}

            **Visualizer Data** (use this to make the playbook highly specific):
            {json.dumps(visualizer_data, indent=2)[:2400]}

            Create a **practical, motivating, and actionable** onboarding playbook.
            Be specific with real names, files, modules, and ownership where available.

            Return **only valid JSON**:

            {{
            "title": "Onboarding Playbook — {role}",
            "welcome_message": "Warm, personal welcome message mentioning the role and excitement...",
            "sections": [
                {{"title": "Week 1 Goals", "content": "Clear, actionable goals..."}},
                {{"title": "Key People & Ownership", "content": "List real people and what they own..."}},
                {{"title": "Core Systems & Architecture", "content": "Summary of important layers..."}},
                {{"title": "Codebase Navigation & Safe Zones", "content": "Key files + safe areas to start..."}},
                {{"title": "Learning Path & First Tasks", "content": "Prioritized steps..."}}
            ]
            }}
        """

        raw = llm_infer(prompt, temperature=0.25, max_tokens=1600)

        try:
            cleaned = raw.strip()
            if cleaned.startswith("```json"): cleaned = cleaned[7:]
            if cleaned.endswith("```"): cleaned = cleaned[:-3]
            playbook = json.loads(cleaned)
        except Exception as e:
            logger.warning(f"JSON parse failed: {e}")
            playbook = self._fallback_playbook(role)

        # Attach full visualizer data (post-LLM, no token cost)
        playbook["visualizer"] = visualizer_data

        # Save to DB
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
            self.supabase.table("playbooks").upsert(record, on_conflict="company_id,role").execute()
            logger.info(f"Playbook saved for {role}")
        except Exception as e:
            logger.error(f"Failed to save playbook: {e}")

        return playbook

    def _gather_compact_context(self, role: str, company_id: str = "default") -> str:
        """Very compact, high-signal context for LLM."""
        parts = []

        # People
        people = self.supabase.table("entities").select("name").eq("type", "PERSON").eq("company_id", company_id).limit(5).execute()
        if people.data:
            parts.append("People: " + ", ".join(p["name"] for p in people.data))

        # Recent activity
        recent = self.supabase.table("raw_data").select("content").eq("company_id", company_id).order("created_at", desc=True).limit(3).execute()
        if recent.data:
            parts.append("Recent: " + " | ".join(r["content"][:80] for r in recent.data))

        # Key files
        files = self.supabase.table("codebase_files").select("file_path").eq("company_id", company_id).limit(6).execute()
        if files.data:
            parts.append("Files: " + ", ".join(f["file_path"] for f in files.data))

        return "\n".join(parts) if parts else "No additional context available."

    def _fallback_playbook(self, role: str) -> Dict:
        return {
            "title": f"Onboarding Playbook — {role}",
            "welcome_message": f"Welcome to the team! We're excited to have you as our new {role}.",
            "sections": []
        }
