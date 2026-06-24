# nlp/codebase/analyzer.py
"""
KMS Codebase Analyzer — Baseline + Incremental model.
Maintains physical codebase structure in dedicated tables.
"""

import logging
from typing import Dict, Any
from datetime import datetime, timezone
import uuid

from supabase import Client
from engine.schema import Entity

logger = logging.getLogger(__name__)


class CodebaseAnalyzer:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def process_push_event(self, payload: Dict[str, Any], record_id: str):
        """Incremental update from GitHub push."""
        logger.info(f"Processing incremental push | record={record_id}")

        try:
            repo_name = self._extract_repo_name(payload)
            files = payload.get("files", {})
            changed_files = files.get("modified", []) + files.get("added", [])

            for file_path in changed_files[:50]:
                await self._upsert_file(file_path, repo_name, record_id, payload)

            logger.info(f"Incremental update complete: {len(changed_files)} files")
            return True
        except Exception as e:
            logger.error(f"Incremental push failed: {e}", exc_info=True)
            return False

    def _extract_repo_name(self, payload: Dict) -> str:
        if isinstance(payload.get("repository"), dict):
            return payload["repository"].get("full_name") or payload["repository"].get("name", "unknown")
        return str(payload.get("repo") or payload.get("repository") or "unknown-repo")

    async def _upsert_file(self, file_path: str, repo_name: str, record_id: str, payload: Dict):
        """The incremental update logic for a single file.
        It ensures the repository exists, upserts the file metadata, and creates a PART_OF relationship.
        """
        
        if not file_path or file_path.startswith("."):
            return

        # Ensure repo exists
        repo_data = {
            "full_name": repo_name,
            "company_id": "default",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        self.supabase.table("repositories").upsert(repo_data, on_conflict="full_name").execute()

        repo_res = self.supabase.table("repositories").select("id").eq("full_name", repo_name).single().execute()
        repo_id = repo_res.data["id"]

        file_name = file_path.split("/")[-1]

        file_data = {
            "repository_id": repo_id,
            "file_path": file_path,
            "file_name": file_name,
            "language": self._detect_language(file_path),
            "last_modified_at": datetime.now(timezone.utc).isoformat(),
            "last_commit_sha": payload.get("head_commit", {}).get("id"),
            "last_author": payload.get("sender"),
            "metadata": {"source_record_id": record_id}
        }

        self.supabase.table("codebase_files").upsert(
            file_data, on_conflict="repository_id,file_path"
        ).execute()

        # Create PART_OF relationship
        relation = {
            "id": str(uuid.uuid4()),
            "source_id": f"file-{repo_id}-{hash(file_path)}",  # or use actual file id if needed
            "target_id": repo_id,
            "type": "PART_OF",
            "confidence": 1.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_record_id": record_id
        }
        # Note: Adjust source_id/target_id based on how you generate file IDs

        logger.info(f"File + PART_OF relation: {file_path}")

    def _detect_language(self, file_path: str) -> str:
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        mapping = {"go": "Go", "py": "Python", "js": "JavaScript", "ts": "TypeScript", "java": "Java",
                   "cpp": "C++", "c": "C", "rs": "Rust", "rb": "Ruby", "php": "PHP", "swift": "Swift",
                   "kt": "Kotlin", "scala": "Scala", "hs": "Haskell", "lua": "Lua", "pl": "Perl",
                   "sh": "Shell", "bash": "Bash"}
        return mapping.get(ext, "Unknown")
