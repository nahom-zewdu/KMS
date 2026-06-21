# nlp/codebase/analyzer.py
"""
KMS Codebase Analyzer — Processes GitHub push events.
Extracts FILE entities and will later build relationships.
"""

import logging
from typing import Dict, Any
import uuid
from datetime import datetime, timezone

from supabase import Client
from engine.schema import Entity   # Use the same schema as NER

logger = logging.getLogger(__name__)


class CodebaseAnalyzer:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def process_push_event(self, payload: Dict[str, Any], record_id: str):
        """Process GitHub push and index all changed files."""
        logger.info(f"Payload received: {payload}")

        try:
            # Robust repo name extraction
            repo_name = "unknown-repo"
            if isinstance(payload.get("repository"), dict):
                repo_name = payload["repository"].get("full_name") or payload["repository"].get("name", "unknown-repo")
            elif payload.get("repo"):
                repo_name = str(payload["repo"])

            files = payload.get("files", {})
            changed_files = (
                files.get("added", []) +
                files.get("modified", []) +
                files.get("removed", [])
            )

            files_processed = 0
            for file_path in changed_files[:50]:
                if file_path:
                    await self._index_file(file_path, repo_name, record_id)
                    files_processed += 1

            logger.info(f"CodebaseAnalyzer: Processed {files_processed} files from {repo_name}")
            return True

        except Exception as e:
            logger.error(f"Codebase analysis failed for {record_id}: {e}", exc_info=True)
            return False

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
            logger.info(f"✅ Indexed file: {file_path} in {repo_name}")
        except Exception as e:
            logger.warning(f"Failed to index {file_path}: {e}")

    def _detect_language(self, file_path: str) -> str:
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        mapping = {
            "go": "Go", "py": "Python", "js": "JavaScript", "ts": "TypeScript",
            "java": "Java", "rs": "Rust", "cpp": "C++", "cs": "C#",
        }
        return mapping.get(ext, "Unknown")
