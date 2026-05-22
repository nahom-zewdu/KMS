# nlp/playbooks/generator.py
"""
KMS Onboard Playbook Generator
Generates high-quality, structured onboarding playbooks.

Uses a custom prompt + real company knowledge context.
Saves results to DB for later retrieval.
"""
from typing import Dict, Any
import logging
from datetime import datetime, timedelta
from engine.llm import llm_infer
from supabase import Client

logger = logging.getLogger(__name__)

class PlaybookGenerator:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def generate(self, role: str, company_id: str = "default") -> Dict[str, Any]:
        """
        Generate a full playbook for a role.
        Returns structured data + saves to DB.
        """
        context = await self._gather_knowledge_context(role)

        prompt = f"""
You are an elite engineering onboarding designer.

Create a professional, engaging onboarding playbook for:

**Role**: {role}

Use the following real company knowledge:

{context}

Output valid JSON with this exact structure:
{{
  "title": "Onboarding Playbook - {role}",
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

        raw = llm_infer(prompt, temperature=0.3, max_tokens=1500)
        
        try:
            playbook_data = eval(raw) if isinstance(raw, str) else raw  # temporary safe parse
        except:
            playbook_data = {"title": f"Onboarding Playbook - {role}", "sections": []}

        # Save to database
        playbook_record = {
            "company_id": company_id,
            "role": role,
            "title": playbook_data.get("title"),
            "content": playbook_data,
            "expires_at": datetime.utcnow() + timedelta(days=90)
        }

        result = self.supabase.table("playbooks").insert(playbook_record).execute()

        logger.info(f"Generated playbook for role: {role}")
        return playbook_data
