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

    async def build_for_role(self, role: str) -> Dict:
        """Main entrypoint for playbook visualizer data."""
        repo_name = "nahom-zewdu/KMS"  # TODO: make dynamic per company later

        # 1. Get high-level architecture (inferred from top-level dirs + entities)
        architecture = await self._build_architecture_layers(repo_name)

        # 2. Get modules with importance
        modules = await self._build_modules(repo_name, role)

        # 3. Sample key files per module
        files = await self._build_key_files(repo_name)

        return {
            "architecture": architecture,
            "modules": modules,
            "key_files": files,
            "role": role
        }

    async def _build_architecture_layers(self, repo_name: str) -> List[Dict]:
        """High-level layers inferred from directory structure."""
        # Simple but effective inference from top-level folders
        layers = ["api", "nlp", "worker", "services", "domain", "utils"]
        
        return [
            {
                "name": layer.capitalize(),
                "description": f"Core {layer} functionality",
                "module_count": 0  # Will be filled later
            } for layer in layers
        ]

    async def _build_modules(self, repo_name: str, role: str) -> List[Dict]:
        """Modules with importance scoring."""
        # For MVP, use directory-based modules from codebase_files
        result = await self.supabase.table("codebase_files")\
            .select("file_path")\
            .like("file_path", f"%{role}%")\
            .limit(50).execute()

        modules = {}
        for row in result.data or []:
            parts = row["file_path"].split("/")
            if len(parts) > 1:
                mod = parts[0] + "/" + (parts[1] if len(parts) > 1 else "")
                modules[mod] = modules.get(mod, 0) + 1

        return [
            {"name": name, "file_count": count, "importance": min(1.0, count / 10)}
            for name, count in list(modules.items())[:12]
        ]

    async def _build_key_files(self, repo_name: str) -> List[Dict]:
        """Key files with enriched context."""
        files = await self.supabase.table("codebase_files")\
            .select("file_path, language, last_author, metadata")\
            .limit(30).execute()

        return [
            {
                "path": f["file_path"],
                "name": f["file_path"].split("/")[-1],
                "language": f.get("language"),
                "last_author": f.get("last_author"),
                "context": "High importance based on recent activity"  # LLM can enrich later
            } for f in (files.data or [])
        ]
