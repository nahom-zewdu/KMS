# nlp/playbooks/generator.py
"""
KMS Onboard Intelligent Playbook Generator
Generates a comprehensive onboarding playbook for new hires based on their role.
Integrates with the knowledge graph to pull relevant context about people, systems, and recent activity.
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
        """
        Generate a complete onboarding playbook for a role.
        """
        context = await self._gather_context(role)

        prompt = f"""
You are an elite onboarding designer for a fast-growing fintech/SaaS company.

Create a world-class onboarding playbook for:

**Role**: {role}
**Employee**: {employee_name or 'New Team Member'}

Use this real company knowledge:

{context}

Output **valid JSON only** with this structure:
{{
  "title": "Onboarding Playbook - {role}",
  "welcome_message": "Friendly welcome...",
  "sections": [
    {{
      "title": "Week 1 Goals",
      "content": "Detailed content here..."
    }},
    {{
      "title": "Key People & Ownership",
      "content": "..."
    }},
    {{
      "title": "Core Systems & Architecture",
      "content": "..."
    }},
    {{
      "title": "Recent Changes & Context",
      "content": "..."
    }},
    {{
      "title": "First Tasks & Milestones",
      "content": "..."
    }}
  ]
}}
"""

        raw_response = llm_infer(prompt, temperature=0.3, max_tokens=1800)

        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            playbook_data = json.loads(cleaned)
        except:
            logger.warning("Failed to parse playbook JSON, using fallback")
            playbook_data = {
                "title": f"Onboarding Playbook - {role}",
                "welcome_message": f"Welcome to the team as a {role}!",
                "sections": []
            }

        # Save to database - FIXED: Convert datetime to string
        expires_at = (datetime.utcnow() + timedelta(days=90)).isoformat()

        record = {
            "company_id": company_id,
            "role": role,
            "title": playbook_data.get("title"),
            "content": playbook_data,
            "generated_for": employee_name,
            "expires_at": expires_at
        }

        try:
            self.supabase.table("playbooks").insert(record).execute()
            logger.info(f"✅ Saved playbook for role: {role}")
        except Exception as e:
            logger.error(f"Failed to save playbook to DB: {e}")

        logger.info(f"✅ Generated playbook for role: {role}")
        return playbook_data

    async def _gather_context(self, role: str) -> str:
        """Gather relevant knowledge from the KG"""
        context = []

        # People
        people = self.supabase.table("entities").select("name").eq("type", "PERSON").limit(12).execute()
        context.append("**Key People:** " + ", ".join([p["name"] for p in people.data or []]))

        # Systems
        systems = self.supabase.table("entities").select("name").eq("type", "SYSTEM").limit(20).execute()
        context.append("**Core Systems:** " + ", ".join([s["name"] for s in systems.data or []]))

        # Recent activity
        recent = self.supabase.table("raw_data").select("content").order("created_at", desc=True).limit(10).execute()
        context.append("**Recent Activity:** " + " | ".join([r["content"][:150] for r in recent.data or []]))

        return "\n\n".join(context)
