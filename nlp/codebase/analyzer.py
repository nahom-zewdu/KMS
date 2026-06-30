# nlp/codebase/analyzer.py
"""
This module provides a service to analyze codebase changes from GitHub push events.
It processes the payload, extracts changed files, and updates the codebase_files table in Supabase
with metadata and PART_OF relationships.
It is designed to handle incremental updates efficiently, ensuring that the codebase representation remains current.
The analyzer is intended to be used in conjunction with a webhook listener that receives GitHub push events.
"""

import logging
from typing import Dict, Any
from datetime import datetime, timezone
import uuid

from supabase import Client

logger = logging.getLogger(__name__)


class CodebaseAnalyzer:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def process_push_event(self, payload: Dict[str, Any], record_id: str):
        """Incremental update from push."""
        logger.info(f"Incremental push | record={record_id}")

        try:
            repo_name = self._extract_repo_name(payload)
            files = payload.get("files", {})
            changed_files = files.get("modified", []) + files.get("added", [])

            for file_path in changed_files[:60]:
                if file_path:
                    await self._upsert_file(file_path, repo_name, record_id, payload)

            logger.info(f"Incremental update: {len(changed_files)} files for {repo_name}")
            return True
        except Exception as e:
            logger.error(f"Incremental failed {record_id}: {e}", exc_info=True)
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

        # Ensure repo
        repo_data = {"full_name": repo_name, "company_id": "default", "updated_at": datetime.now(timezone.utc).isoformat()}
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

        self.supabase.table("codebase_files").upsert(file_data, on_conflict="repository_id,file_path").execute()

        # Create PART_OF relationship
        self.supabase.table("edges").upsert({
            "id": str(uuid.uuid4()),
            "source_id": f"file-{repo_id}-{hash(file_path)}",  # temporary
            "target_id": repo_id,
            "type": "PART_OF",
            "confidence": 1.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_record_id": record_id
        }, on_conflict="id").execute()

        logger.info(f"Updated file + PART_OF: {file_path}")
