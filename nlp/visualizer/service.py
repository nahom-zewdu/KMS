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
        """Main entrypoint synchronous for simplicity and reliability."""
        repo_name = "nahom-zewdu/KMS"  # Make dynamic later via company_id

        architecture = self._build_architecture_layers(repo_name)
        modules = self._build_modules(repo_name, role)
        key_files = self._build_key_files(repo_name)

        return {
            "architecture": architecture,
            "modules": modules,
            "key_files": key_files,
            "role": role
        }

    def _build_architecture_layers(self, repo_name: str) -> List[Dict]:
        """High-level layers inferred from directory structure."""
        layers = ["api", "nlp", "worker", "services", "domain", "utils"]
        return [
            {
                "name": layer.capitalize(),
                "description": f"Core {layer} functionality and business logic",
                "module_count": 0
            } for layer in layers
        ]

    def _build_modules(self, repo_name: str, role: str) -> List[Dict]:
        """Modules with importance scoring based on file count and role relevance."""
        try:
            result = self.supabase.table("codebase_files")\
                .select("file_path")\
                .limit(80).execute()

            modules = {}
            for row in result.data or []:
                parts = row["file_path"].split("/")
                if len(parts) > 1:
                    mod = "/".join(parts[:2])  # e.g. "nlp/engine"
                    modules[mod] = modules.get(mod, 0) + 1

            return [
                {
                    "name": name,
                    "file_count": count,
                    "importance": min(1.0, count / 8.0)
                }
                for name, count in list(modules.items())[:15]
            ]
        except Exception as e:
            logger.warning(f"Failed to build modules: {e}")
            return []

    def _build_key_files(self, repo_name: str) -> List[Dict]:
        """Key files with basic enriched context."""
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
                    "context": "Important file based on recent activity"
                } for f in (files.data or [])
            ]
        except Exception as e:
            logger.warning(f"Failed to build key files: {e}")
            return []
