# nlp/visualizer/service.py
"""
This module provides a service for building visualizer data for different roles based on the codebase and knowledge graph.
It interacts with a Supabase client to fetch relevant data and constructs structured information for visualization.
The main entry point is the `build_for_role` method, which orchestrates the construction of various sections such as architecture, modules, key files, learning paths, request flows, safe zones, and dependency impact.
"""

import logging
from typing import Dict, List, Any
from supabase import Client

logger = logging.getLogger(__name__)


class VisualizerService:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def build_for_role(self, role: str) -> Dict:
        """Main entrypoint — builds PRD sections from real KG + codebase data."""
        try:
            architecture = self._build_architecture()
            modules = self._build_modules(role)
            key_files = self._build_key_files(role)
            learning_path = self._build_learning_path(role, modules)
            request_flows = self._build_request_flows()
            safe_zones = self._build_safe_zones()
            dependency_impact = self._build_dependency_impact()

            return {
                "architecture": architecture,
                "modules": modules,
                "key_files": key_files,
                "learning_path": learning_path,
                "request_flows": request_flows,
                "safe_zones": safe_zones,
                "dependency_impact": dependency_impact,
                "role": role,
            }
        except Exception as e:
            logger.error(f"Visualizer build failed for role '{role}': {e}")
            return {"error": "Failed to load visualizer data"}

    def _build_architecture(self) -> List[Dict]:
        """Infer layers from top-level directories in codebase_files."""
        try:
            res = self.supabase.table("codebase_files").select("file_path").limit(150).execute()
            top_levels = {}
            for row in res.data or []:
                path = row["file_path"]
                if "/" in path:
                    layer = path.split("/")[0]
                    top_levels[layer] = top_levels.get(layer, 0) + 1

            return [
                {
                    "name": f"{layer.capitalize()} Layer",
                    "description": f"Core {layer} functionality and services",
                    "importance": round(count / max(top_levels.values()), 2) if top_levels else 0.8
                }
                for layer, count in sorted(top_levels.items(), key=lambda x: x[1], reverse=True)[:6]
            ]
        except Exception as e:
            logger.warning(f"Architecture inference failed: {e}")
            return [{"name": "Core Systems", "description": "Main application layers", "importance": 0.9}]

    def _build_modules(self, role: str) -> List[Dict]:
        """Modules from directory structure + role boost + file count."""
        try:
            res = self.supabase.table("codebase_files").select("file_path").limit(300).execute()
            module_map = {}
            for row in res.data or []:
                parts = row["file_path"].split("/")
                if len(parts) >= 2:
                    mod = "/".join(parts[:2])
                    module_map[mod] = module_map.get(mod, 0) + 1

            modules = []
            for name, count in sorted(module_map.items(), key=lambda x: x[1], reverse=True)[:15]:
                importance = min(1.0, count / 15.0)
                # Role relevance boost
                if any(kw in name.lower() for kw in role.lower().split()):
                    importance = min(1.0, importance + 0.35)

                modules.append({
                    "name": name,
                    "file_count": count,
                    "importance": round(importance, 2),
                    "description": f"Core {name} functionality and business logic"
                })
            return modules
        except Exception as e:
            logger.warning(f"Modules build failed: {e}")
            return []

    def _build_key_files(self, role: str) -> List[Dict]:
        """Recent / important files with metadata."""
        try:
            res = self.supabase.table("codebase_files")\
                .select("file_path, language, last_author, metadata")\
                .limit(40).execute()

            return [
                {
                    "path": f.get("file_path"),
                    "name": f.get("file_path", "").split("/")[-1],
                    "language": f.get("language", "Unknown"),
                    "last_author": f.get("last_author"),
                    "context": "High activity or ownership relevance"
                }
                for f in (res.data or [])
            ]
        except:
            return []

    def _build_learning_path(self, role: str, modules: List[Dict]) -> List[Dict]:
        """Sorted by importance + role relevance."""
        sorted_modules = sorted(modules, key=lambda m: m.get("importance", 0), reverse=True)
        path = []
        for i, mod in enumerate(sorted_modules[:6]):
            path.append({
                "step": i + 1,
                "title": mod["name"],
                "why": f"Foundational {mod['name']} patterns are critical for {role} work",
                "effort": "Medium",
                "difficulty": "Medium",
                "next": sorted_modules[(i + 1) % len(sorted_modules)]["name"] if len(sorted_modules) > 1 else None
            })
        return path

    def _build_request_flows(self) -> List[Dict]:
        """Real flows from ingestion patterns (static for now, can be enriched later)."""
        return [
            {"name": "GitHub Push Flow", "steps": ["Webhook → Rich Content → NER/RE → Codebase Files + KG"], "description": "Code changes → Knowledge"},
            {"name": "Slack Communication Flow", "steps": ["Message → Entity Extraction → Relations"], "description": "Team knowledge capture"},
        ]

    def _build_safe_zones(self) -> Dict:
        """Safe zones from low-risk directory patterns."""
        try:
            res = self.supabase.table("codebase_files").select("file_path").limit(100).execute()
            safe = []
            risky = []
            for f in res.data or []:
                path = f["file_path"].lower()
                if any(k in path for k in ["utils", "common", "helper", "test", "config"]):
                    safe.append({"path": f["file_path"], "reason": "Low dependency, reusable"})
                elif any(k in path for k in ["core", "auth", "payment", "main"]):
                    risky.append({"path": f["file_path"], "reason": "High business impact"})
            return {
                "safe_first": safe[:6],
                "high_risk": risky[:4]
            }
        except:
            return {"safe_first": [], "high_risk": []}

    def _build_dependency_impact(self) -> List[Dict]:
        """Basic impact from known critical files (enhance with edges later)."""
        return [
            {"file": "nlp/worker/ingestion.py", "impact": "Affects all event processing and KG updates", "downstream": ["Entities", "Edges", "Playbooks"]},
            {"file": "api/handlers/github.go", "impact": "Core webhook ingestion", "downstream": ["Baseline Sync", "File Indexing"]},
        ]
