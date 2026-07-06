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
        """Main entrypoint."""
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
            logger.error(f"Visualizer build failed for '{role}': {e}")
            return {"error": "Failed to load visualizer data"}

    def _build_architecture(self) -> List[Dict]:
        """Top-level layers from codebase_files."""
        try:
            res = self.supabase.table("codebase_files").select("file_path").limit(200).execute()
            layers = {}
            for row in res.data or []:
                if "/" in row["file_path"]:
                    layer = row["file_path"].split("/")[0]
                    layers[layer] = layers.get(layer, 0) + 1

            return [
                {
                    "name": f"{layer.capitalize()} Layer",
                    "description": f"Core {layer} functionality",
                    "importance": round(count / max(layers.values() or [1]), 2)
                }
                for layer, count in sorted(layers.items(), key=lambda x: x[1], reverse=True)[:6]
            ]
        except:
            return [{"name": "Core Systems", "description": "Main application", "importance": 0.9}]

    def _build_modules(self, role: str) -> List[Dict]:
        """Use pre-computed modules from codebase_modules table."""
        try:
            res = self.supabase.table("codebase_modules")\
                .select("module_name, module_path, importance_score, inferred_type, description")\
                .order("importance_score", desc=True)\
                .limit(15).execute()

            modules = []
            for m in res.data or []:
                importance = m.get("importance_score", 0.5)
                # Role boost
                if any(kw in m["module_path"].lower() for kw in role.lower().split()):
                    importance = min(1.0, importance + 0.3)

                modules.append({
                    "name": m["module_name"],
                    "path": m["module_path"],
                    "importance": round(importance, 2),
                    "type": m.get("inferred_type", "feature"),
                    "description": m.get("description", f"Core {m['module_name']} module")
                })
            return modules
        except Exception as e:
            logger.warning(f"Modules query failed: {e}")
            # Fallback to file-based inference
            return self._fallback_modules(role)

    def _fallback_modules(self, role: str) -> List[Dict]:
        """Fallback when modules table is empty."""
        try:
            res = self.supabase.table("codebase_files").select("file_path").limit(300).execute()
            module_map = {}
            for row in res.data or []:
                parts = row["file_path"].split("/")
                if len(parts) >= 2:
                    mod = "/".join(parts[:2])
                    module_map[mod] = module_map.get(mod, 0) + 1

            return [
                {
                    "name": name.split("/")[-1],
                    "path": name,
                    "importance": round(min(1.0, count / 15.0), 2),
                    "description": f"Core {name} functionality"
                }
                for name, count in sorted(module_map.items(), key=lambda x: x[1], reverse=True)[:12]
            ]
        except:
            return []

    def _build_key_files(self, role: str) -> List[Dict]:
        """Important files from codebase_files."""
        try:
            res = self.supabase.table("codebase_files")\
                .select("file_path, language, last_author, module_path")\
                .limit(30).execute()

            return [
                {
                    "path": f["file_path"],
                    "name": f["file_path"].split("/")[-1],
                    "language": f.get("language", "Unknown"),
                    "module": f.get("module_path", ""),
                    "context": "Relevant for onboarding"
                }
                for f in (res.data or [])
            ]
        except:
            return []

    def _build_learning_path(self, role: str, modules: List[Dict]) -> List[Dict]:
        """Role-aware learning path from modules."""
        sorted_modules = sorted(modules, key=lambda m: m.get("importance", 0), reverse=True)
        return [
            {
                "step": i + 1,
                "title": mod.get("name") or mod.get("path"),
                "why": f"High importance for {role} responsibilities",
                "effort": "Medium",
                "difficulty": "Medium"
            }
            for i, mod in enumerate(sorted_modules[:6])
        ]

    def _build_request_flows(self) -> List[Dict]:
        return [
            {"name": "GitHub Push Flow", "steps": ["Webhook → Ingestion → NER/RE → Codebase Update"], "description": "Code changes become knowledge"},
            {"name": "Slack Event Flow", "steps": ["Message → Entity Extraction → Relations"], "description": "Team communication captured"},
        ]

    def _build_safe_zones(self) -> Dict:
        """Safe zones from low-risk paths."""
        try:
            res = self.supabase.table("codebase_files").select("file_path").limit(100).execute()
            safe = [f for f in (res.data or []) if any(k in f["file_path"].lower() for k in ["utils", "common", "helper", "test"])]
            risky = [f for f in (res.data or []) if any(k in f["file_path"].lower() for k in ["core", "auth", "main", "payment"])]
            return {
                "safe_first": [{"path": f["file_path"]} for f in safe[:6]],
                "high_risk": [{"path": f["file_path"]} for f in risky[:4]]
            }
        except:
            return {"safe_first": [], "high_risk": []}

    def _build_dependency_impact(self) -> List[Dict]:
        return [
            {"file": "nlp/worker/ingestion.py", "impact": "Affects all event processing", "downstream": ["KG", "Playbooks"]},
            {"file": "api/handlers/github.go", "impact": "Core webhook handling", "downstream": ["Baseline Sync", "File Indexing"]},
        ]
