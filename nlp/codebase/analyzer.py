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
        """the upsert_file method is responsible for inserting or updating a file record in the database. It first checks if the file path is valid and not hidden. 
        Then, it ensures that the repository exists in the database, retrieves its ID, and constructs a file record with relevant information such as file path, name, language, last modified time, last commit SHA, and author. 
        Finally, it upserts the file record into the 'codebase_files' table and logs the update."""
        
        if not file_path or file_path.startswith("."):
            return

        # First ensure repository exists
        repo_record = {
            "full_name": repo_name,
            "company_id": "default",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        self.supabase.table("repositories").upsert(repo_record, on_conflict="full_name").execute()

        # Get repo id
        repo = self.supabase.table("repositories").select("id").eq("full_name", repo_name).single().execute()
        repo_id = repo.data["id"]

        file_name = file_path.split("/")[-1]

        file_record = {
            "repository_id": repo_id,
            "file_path": file_path,
            "file_name": file_name,
            "language": self._detect_language(file_path),
            "last_modified_at": datetime.now(timezone.utc).isoformat(),
            "last_commit_sha": payload.get("head_commit", {}).get("id"),
            "last_author": payload.get("sender"),
            "metadata": {"source_record_id": record_id}
        }

        self.supabase.table("codebase_files").upsert(file_record, on_conflict="repository_id,file_path").execute()

        logger.info(f"Updated file: {file_path} in {repo_name}")

    async def _index_file(self, file_path: str, repo_name: str, record_id: str):
        """Index file using unified Entity schema."""
        if not file_path or file_path.startswith("."):
            return

        file_name = file_path.split("/")[-1]

        entity = Entity(
            text=file_path.lower(),
            type="FILE",
            confidence=1.0,
            record_id=record_id,
            source="github",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        db_entity = entity.to_db_record()

        db_entity.update({
            "file_path": file_path,
            "language": self._detect_language(file_path),
            "metadata": {
                **(db_entity.get("metadata") or {}),
                "repo": repo_name,
                "file_name": file_name,
            }
        })

        try:
            self.supabase.table("entities").upsert(db_entity, on_conflict="id").execute()
            logger.info(f"Indexed file: {file_path} in {repo_name}")
        except Exception as e:
            logger.warning(f"Failed to index {file_path}: {e}")

    def _detect_language(self, file_path: str) -> str:
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        mapping = {
            "go": "Go", "py": "Python", "js": "JavaScript", "ts": "TypeScript",
            "java": "Java", "rs": "Rust", "cpp": "C++", "cs": "C#",
        }
        return mapping.get(ext, "Unknown")
