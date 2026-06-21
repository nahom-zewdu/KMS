# nlp/codebase/analyzer.py
"""
KMS Codebase Analyzer Builds structured understanding of GitHub repositories.
Processes GitHub push events to extract file and module entities, their relationships, and metadata.
This structured knowledge enables advanced codebase queries and insights.
"""

import logging
from typing import Dict, List
import uuid
from datetime import timezone, datetime
from supabase import Client

from engine.schema import Entity  # IMPORTANT: unify schema usage

logger = logging.getLogger(__name__)


class CodebaseAnalyzer:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def process_push_event(self, payload: Dict, record_id: str):
        """Process GitHub push event and index files."""
        logger.info(f"Payload: {payload}")

        try:
            # Robust repo name extraction
            repo_obj = payload.get("repository") or payload.get("repo") or {}
            repo_name = (
                repo_obj.get("full_name")
                or repo_obj.get("name")
                or payload.get("repo")
                or "unknown-repo"
            )

            files = payload.get("files", {})
            changed_files = (
                files.get("added", [])
                + files.get("modified", [])
                + files.get("removed", [])
            )

            files_processed = 0
            for file_path in changed_files[:50]:  # generous limit
                await self._index_file(file_path, repo_name, record_id)
                files_processed += 1

            logger.info(f"CodebaseAnalyzer: Processed {files_processed} files from {repo_name}")
            return True

        except Exception as e:
            logger.error(f"Codebase analysis failed for record {record_id}: {e}")
            return False

    async def _index_file(self, file_path: str, repo_name: str, record_id: str):
        """Index a file using SAME Entity schema as NER (source of truth)."""

        if not file_path or file_path.startswith("."):
            return

        file_name = file_path.split("/")[-1]

        entity = Entity(
            text=file_path.lower(),   # IMPORTANT: full path = stable identity
            type="FILE",
            confidence=1.0,
            record_id=record_id,
            source="github",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        db_entity = entity.to_db_record()

        # enrich metadata properly
        db_entity["metadata"]["repo"] = repo_name
        db_entity["metadata"]["file_name"] = file_name
        db_entity["file_path"] = file_path

        try:
            self.supabase.table("entities") \
                .upsert(db_entity, on_conflict="id") \
                .execute()

            logger.info(f"Indexed file entity: {file_path}")

        except Exception as e:
            logger.warning(f"Failed to index file {file_path}: {e}")

    def _detect_language(self, file_path: str) -> str:
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        mapping = {
            "go": "Go",
            "py": "Python",
            "js": "JavaScript",
            "ts": "TypeScript",
            "java": "Java",
            "rs": "Rust",
            "cpp": "C++",
            "cs": "C#",
        }
        return mapping.get(ext, "Unknown")
