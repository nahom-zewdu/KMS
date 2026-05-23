# nlp/playbooks/generator.py
"""
KMS Onboard Enhanced & Production-Ready Playbook Generator
This module defines the PlaybookGenerator class, which creates rich, actionable onboarding playbooks for new hires based on their role. It gathers real company context (people, systems, recent activity) from the Supabase database and uses a large language model to generate a detailed playbook. The generated playbook is then saved back to the database for future reference.
"""
import json
from typing import Dict, Any
import logging
from datetime import datetime, timedelta
from engine.llm import llm_infer
from supabase import Client

logger = logging.getLogger(__name__)

class PlaybookGenerator:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def generate(self, role: str, company_id: str = "default", employee_name: str = None) -> Dict[str, Any]:
        context = await self._gather_rich_context(role)

        prompt = f"""
          You are a world-class engineering onboarding designer.

          Create an outstanding, specific, and actionable onboarding playbook.

          **Role**: {role}
          **New Hire**: {employee_name or "New Engineer"}

          Use this real company data:

          {context}

          ### Output Requirements:
          - Professional yet friendly tone
          - Very specific (use real names and systems)
          - Actionable advice
          - No generic filler content

          Return **valid JSON only**:

          {{
            "title": "Onboarding Playbook — {role}",
            "welcome_message": "Warm and motivating welcome...",
            "sections": [
              {{
                "title": "Welcome & First Week",
                "content": "..."
              }},
              {{
                "title": "Key People & Ownership",
                "content": "..."
              }},
              {{
                "title": "Core Systems You Should Know",
                "content": "..."
              }},
              {{
                "title": "Recent Context & Changes",
                "content": "..."
              }},
              {{
                "title": "Your First Tasks",
                "content": "..."
              }}
            ]
          }}
          """

        raw_response = llm_infer(prompt, temperature=0.3, max_tokens=2000)

        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            playbook_data = json.loads(cleaned)
        except Exception as e:
            logger.warning(f"JSON parsing failed: {e}")
            playbook_data = self._fallback_playbook(role)

        # Save to DB
        record = {
            "company_id": company_id,
            "role": role.lower().replace(" ", "-"),
            "title": playbook_data.get("title", f"Onboarding Playbook - {role}"),
            "content": playbook_data,
            "generated_for": employee_name,
            "expires_at": (datetime.utcnow() + timedelta(days=90)).isoformat()
        }

        try:
            self.supabase.table("playbooks").insert(record).execute()
        except Exception as e:
            logger.error(f"Failed to save playbook: {e}")

        logger.info(f"✅ Generated enhanced playbook for: {role}")
        return playbook_data

    def _fallback_playbook(self, role: str) -> Dict:
        return {
            "title": f"Onboarding Playbook — {role}",
            "welcome_message": f"Welcome to the team as a {role}!",
            "sections": []
        }

    async def _gather_rich_context(self, role: str) -> str:
        context = []

        # People
        people = self.supabase.table("entities").select("name").eq("type", "PERSON").limit(12).execute()
        if people.data:
            context.append("**People:** " + ", ".join(p["name"] for p in people.data))

        # Systems
        systems = self.supabase.table("entities").select("name").eq("type", "SYSTEM").limit(15).execute()
        if systems.data:
            context.append("**Systems:** " + ", ".join(s["name"] for s in systems.data))

        # Recent Activity
        recent = self.supabase.table("raw_data").select("content").order("created_at", desc=True).limit(12).execute()
        if recent.data:
            recent_text = " | ".join(r["content"][:120] for r in recent.data)
            context.append("**Recent Activity:** " + recent_text)

        return "\n\n".join(context)
