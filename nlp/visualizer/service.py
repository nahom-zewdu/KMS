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
        """Main entrypoint for progressive disclosure."""
        try:
            repo_name = "nahom-zewdu/KMS"  # TODO: dynamic via company_id

            architecture = self._build_architecture()
            modules = self._build_modules(role)
            key_files = self._build_key_files(role)

            return {
                "architecture": architecture,
                "modules": modules,
                "key_files": key_files,
                "role": role,
                "recommended_start": self._recommended_start(modules, role)
            }
        except Exception as e:
            logger.error(f"Visualizer build failed: {e}")
            return {"error": "Failed to load visualizer"}

    def _build_architecture(self) -> List[Dict]:
        """High-level system layers inferred from data."""
        return [
            {"name": "API Layer", "description": "Handles incoming requests and routing", "importance": 0.95},
            {"name": "Business Logic", "description": "Core domain services", "importance": 0.9},
            {"name": "Knowledge Engine", "description": "NLP, entity extraction, graph", "importance": 0.85},
            {"name": "Worker Layer", "description": "Background ingestion and processing", "importance": 0.8},
        ]

    def _build_modules(self, role: str) -> List[Dict]:
        """Modules inferred from codebase_files + role relevance."""
        try:
            files = self.supabase.table("codebase_files")\
                .select("file_path")\
                .limit(150).execute()

            module_map = {}
            for f in files.data or []:
                parts = f["file_path"].split("/")
                if len(parts) >= 2:
                    mod = "/".join(parts[:2])
                    module_map[mod] = module_map.get(mod, 0) + 1

            modules = []
            for name, count in sorted(module_map.items(), key=lambda x: x[1], reverse=True)[:12]:
                importance = min(1.0, count / 10)
                # Role boost
                if any(kw in name.lower() for kw in role.lower().split()):
                    importance = min(1.0, importance + 0.35)
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
        """Key files with enriched context."""
        try:
            files = self.supabase.table("codebase_files")\
                .select("file_path, language, last_author")\
                .limit(40).execute()

            return [
                {
                    "path": f["file_path"],
                    "name": f["file_path"].split("/")[-1],
                    "language": f.get("language", "Unknown"),
                    "last_author": f.get("last_author"),
                } for f in (files.data or [])
            ]
        except:
            return []

    def _recommended_start(self, modules: List, role: str) -> str:
        """Role-aware starting recommendation."""
        if "backend" in role.lower():
            return "Start with API Layer and Business Logic modules."
        return "Begin with the highest importance modules shown above."
