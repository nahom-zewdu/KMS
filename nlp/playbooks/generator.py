# nlp/playbooks/generator.py
"""
KMS Onboard — Enhanced Playbook Generator
Improved prompt, richer context, better structure, and cleaner JSON handling.
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
        Generate a high-quality, structured onboarding playbook.
        """
        context = await self._gather_rich_context(role)

        prompt = f"""
        You are an elite onboarding designer at a high-growth fintech/SaaS company.

        Create a **world-class** onboarding playbook for:

        **Role**: {role}
        **New Hire**: {employee_name or 'New Team Member'}

        Use this real company knowledge to make it specific and useful:

        {context}

        ### Requirements:
        - Make it professional, encouraging, and actionable.
        - Use real names, systems, and recent activity from the data.
        - Be specific (no generic advice).
        - Keep tone friendly but professional.

        Output **valid JSON only** with this exact structure:

        {{
          "title": "Onboarding Playbook - {role}",
          "welcome_message": "Warm, personalized welcome message...",
          "sections": [
            {{
              "title": "Week 1 Goals & Priorities",
              "content": "Clear, actionable goals..."
            }},
            {{
              "title": "Key People & Who to Talk To",
              "content": "List of important people with their responsibilities..."
            }},
            {{
              "title": "Core Systems & Architecture",
              "content": "Most important services and how they connect..."
            }},
            {{
              "title": "Recent Changes & Context",
              "content": "Important recent updates..."
            }},
            {{
              "title": "First Tasks & Milestones",
              "content": "Suggested first contributions..."
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
            logger.warning(f"JSON parse failed: {e}. Using fallback.")
            playbook_data = {
                "title": f"Onboarding Playbook - {role}",
                "welcome_message": f"Welcome to the team as a {role}!",
                "sections": []
            }

        # Save to database
        record = {
            "company_id": company_id,
            "role": role.lower().replace(" ", "-"),
            "title": playbook_data.get("title"),
            "content": playbook_data,
            "generated_for": employee_name,
            "expires_at": (datetime.utcnow() + timedelta(days=90)).isoformat()
        }

        try:
            self.supabase.table("playbooks").insert(record).execute()
            logger.info(f"✅ Saved playbook for role: {role}")
        except Exception as e:
            logger.error(f"Failed to save playbook: {e}")

        logger.info(f"✅ Generated rich playbook for role: {role}")
        return playbook_data

    async def _gather_rich_context(self, role: str) -> str:
        """Gather rich, useful context from the KG"""
        context = []

        # 1. People
        people = self.supabase.table("entities").select("name,metadata").eq("type", "PERSON").limit(15).execute()
        if people.data:
            people_list = [f"- {p['name']}" for p in people.data]
            context.append("**Key People:**\n" + "\n".join(people_list))

        # 2. Systems
        systems = self.supabase.table("entities").select("name,metadata").eq("type", "SYSTEM").limit(20).execute()
        if systems.data:
            systems_list = [f"- {s['name']}" for s in systems.data]
            context.append("**Core Systems:**\n" + "\n".join(systems_list))

        # 3. Recent Activity (very important)
        recent = self.supabase.table("raw_data").select("content,created_at,source").order("created_at", desc=True).limit(12).execute()
        if recent.data:
            recent_list = [f"- {r['content'][:180]}" for r in recent.data]
            context.append("**Recent Activity:**\n" + "\n".join(recent_list))

        return "\n\n".join(context)
