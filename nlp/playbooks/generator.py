# nlp/playbooks/generator.py
"""
KMS Onboard — Production-Ready Playbook Generator
Pulls from both semantic KG (entities/edges) and physical codebase (codebase_files).
Generates rich, actionable, role-specific playbooks.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from engine.llm import llm_infer
from supabase import Client

logger = logging.getLogger(__name__)


class PlaybookGenerator:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def generate(self, role: str, company_id: str = "default", employee_name: str = None) -> Dict[str, Any]:
        context = self._gather_rich_context(role)  # synchronous for now

        prompt = f"""
            You are an elite engineering onboarding architect.
            Create a world-class, highly specific onboarding playbook for a new {role}.

            **Company Context**:
            {context}

            **Requirements**:
            - Warm, professional, motivating tone
            - Extremely specific (real names, systems, files, recent changes)
            - Actionable first-week plan
            - Highlight key codebase files

            Return **only valid JSON**:
            {{
            "title": "Onboarding Playbook — {role}",
            "welcome_message": "Warm welcome...",
            "sections": [
                {{"title": "Week 1 Goals", "content": "..."}},
                {{"title": "Key People & Ownership", "content": "..."}},
                {{"title": "Core Systems & Codebase", "content": "..."}},
                {{"title": "Recent Changes", "content": "..."}},
                {{"title": "Your First Tasks", "content": "..."}}
            ]
            }}
            """

        raw = llm_infer(prompt, temperature=0.3, max_tokens=2500)
        
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```json"): cleaned = cleaned[7:]
            if cleaned.endswith("```"): cleaned = cleaned[:-3]
            playbook = json.loads(cleaned)
        except Exception as e:
            logger.warning(f"JSON parse failed: {e}")
            playbook = self._fallback_playbook(role)

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
            self.supabase.table("playbooks").insert(record).execute()
        except Exception as e:
            logger.error(f"Failed to save playbook: {e}")

        logger.info(f"Playbook generated for {role}")
        return playbook

    def _fallback_playbook(self, role: str) -> Dict:
        return {
            "title": f"Onboarding Playbook — {role}",
            "welcome_message": f"Welcome to the team as our new {role}!",
            "sections": []
        }

    def _gather_rich_context(self, role: str) -> str:
        """Synchronous context gathering."""
        parts = []

        # People
        people = self.supabase.table("entities").select("name").eq("type", "PERSON").limit(12).execute()
        if people.data:
            parts.append("**Key People:** " + ", ".join(p["name"] for p in people.data))

        # Systems
        systems = self.supabase.table("entities").select("name").eq("type", "SYSTEM").limit(12).execute()
        if systems.data:
            parts.append("**Core Systems:** " + ", ".join(s["name"] for s in systems.data))

        # Codebase Files (new physical layer)
        files = self.supabase.table("codebase_files")\
            .select("file_path, language")\
            .limit(25).execute()
        if files.data:
            code_list = "\n".join([f"- {f['file_path']} ({f.get('language', 'Unknown')})" for f in files.data[:15]])
            parts.append(f"**Key Codebase Files:**\n{code_list}")

        # Recent Activity
        recent = self.supabase.table("raw_data").select("content")\
            .order("created_at", desc=True).limit(8).execute()
        if recent.data:
            parts.append("**Recent Activity:** " + " | ".join(r["content"][:100] for r in recent.data))

        return "\n\n".join(parts)
        
    async def _gather_codebase_context(self, role: str) -> str:
        # Query relevant files for this role
        files = self.supabase.table("codebase_files")\
            .select("file_path, language, metadata")\
            .limit(30).execute()

        context = ["### Codebase Overview"]
        for f in files.data:
            context.append(f"- {f['file_path']} ({f.get('language', 'Unknown')})")

        return "\n".join(context)
