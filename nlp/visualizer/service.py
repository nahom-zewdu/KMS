# nlp/visualizer/service.py

"""
This module provides a service to build visualizer data for onboarding playbooks.
It gathers high-level architecture, modules, and key files from the codebase,
and enriches them with context for a specific role.
The visualizer data is used to generate actionable and role-specific onboarding playbooks.
"""

import logging
from typing import Dict, List, Any
from supabase import Client

logger = logging.getLogger(__name__)


class VisualizerService:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def build_for_role(self, role: str) -> Dict:
        """Main entrypoint — returns structured data for progressive disclosure."""
        try:
            repo_name = "nahom-zewdu/KMS"  # TODO: Make dynamic via company_id later

            architecture = self._build_architecture_layers()
            modules = self._build_modules(role)
            key_files = self._build_key_files(role)

            return {
                "architecture": architecture,
                "modules": modules,
                "key_files": key_files,
                "role": role,
                "recommendation": self._generate_role_recommendation(role, modules)
            }
        except Exception as e:
            logger.error(f"Visualizer build failed for {role}: {e}")
            return {"error": "Failed to load visualizer data"}

    def _build_architecture_layers(self) -> List[Dict]:
        """High-level architecture inferred from directory + entities."""
        return [
            {"name": "API Layer", "description": "Handles incoming requests and routing", "importance": 0.95},
            {"name": "Business Logic", "description": "Core domain services and workflows", "importance": 0.9},
            {"name": "Knowledge Engine", "description": "NLP, entity extraction, and graph building", "importance": 0.85},
            {"name": "Worker Layer", "description": "Background processing and ingestion", "importance": 0.8},
            {"name": "Infrastructure", "description": "Storage, Redis, Supabase", "importance": 0.7},
        ]

    def _build_modules(self, role: str) -> List[Dict]:
        """Role-aware modules with importance."""
        try:
            files = self.supabase.table("codebase_files")\
                .select("file_path, language")\
                .limit(120).execute()

            module_map = {}
            for f in files.data or []:
                parts = f["file_path"].split("/")
                if len(parts) >= 2:
                    mod = "/".join(parts[:2])
                    module_map[mod] = module_map.get(mod, 0) + 1

            # Simple role-based boost
            role_keywords = role.lower().split()
            modules = []
            for name, count in sorted(module_map.items(), key=lambda x: x[1], reverse=True)[:12]:
                importance = min(1.0, count / 12)
                if any(kw in name.lower() for kw in role_keywords):
                    importance = min(1.0, importance + 0.3)
                modules.append({
                    "name": name,
                    "file_count": count,
                    "importance": round(importance, 2),
                    "description": f"Core {name} functionality"
                })
            return modules
        except Exception as e:
            logger.warning(f"Module build failed: {e}")
            return []

    def _build_key_files(self, role: str) -> List[Dict]:
        """Key files with context."""
        try:
            files = self.supabase.table("codebase_files")\
                .select("file_path, language, last_author, metadata")\
                .limit(40).execute()

            return [
                {
                    "path": f["file_path"],
                    "name": f["file_path"].split("/")[-1],
                    "language": f.get("language", "Unknown"),
                    "last_author": f.get("last_author"),
                    "context": "High relevance for new developers"
                } for f in (files.data or [])
            ]
        except:
            return []

    def _generate_role_recommendation(self, role: str, modules: List) -> str:
        """Role-specific starting advice."""
        if "backend" in role.lower():
            return "Start with API Layer and Business Logic modules."
        if "frontend" in role.lower():
            return "Focus on UI components and API integration files."
        return "Begin with high-importance modules shown above."
