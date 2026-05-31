# nlp/codebase/analyzer.py
"""
KMS Codebase Analyzer Builds structured understanding of GitHub repositories.
Processes GitHub push events to extract file and module entities, their relationships, and metadata.
This structured knowledge enables advanced codebase queries and insights.
"""

import logging
from typing import Dict, List, Any
from supabase import Client

logger = logging.getLogger(__name__)

class CodebaseAnalyzer:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def process_push_event(self, payload: Dict, record_id: str):
        """Process GitHub push and extract file/module entities + relationships."""
        try:
            repo_name = payload.get("repository", {}).get("full_name", "unknown")
            commits = payload.get("commits", [])

            files_processed = 0

            for commit in commits:
                # Get all changed files
                changed_files = (
                    commit.get("added", []) +
                    commit.get("modified", []) 
                )

                for file_path in changed_files[:50]:  # Limit per push
                    await self._index_file(file_path, repo_name, record_id)
                    files_processed += 1

            logger.info(f"CodebaseAnalyzer: Processed {files_processed} files from {repo_name}")
            return True

        except Exception as e:
            logger.error(f"Codebase analysis failed: {e}")
            return False

    async def _index_file(self, file_path: str, repo_name: str, record_id: str):
        """Index a single file as entity and create relationships."""
        file_name = file_path.split("/")[-1]
        language = self._detect_language(file_path)

        # Create or update FILE entity
        entity = {
            "id": f"file-{hash(file_path)}",
            "type": "FILE",
            "name": file_name,
            "file_path": file_path,
            "language": language,
            "metadata": {
                "repo": repo_name,
                "source_record_id": record_id
            }
        }

        try:
            self.supabase.table("entities").upsert(entity, on_conflict="id").execute()

            # Create CONTAINS relationship with repo (if repo entity exists)
            # We'll create repo entity on first push
            await self._ensure_repo_entity(repo_name)

            logger.debug(f"Indexed file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to index file {file_path}: {e}")

    def _detect_language(self, file_path: str) -> str:
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        lang_map = {
            "go": "Go", "py": "Python", "js": "JavaScript", "ts": "TypeScript",
            "java": "Java", "rs": "Rust", "cpp": "C++", "cs": "C#", "php": "PHP"
        }
        return lang_map.get(ext, "Unknown")

    async def _ensure_repo_entity(self, repo_name: str):
        """Ensure repository entity exists."""
        entity = {
            "id": f"repo-{hash(repo_name)}",
            "type": "REPOSITORY",
            "name": repo_name,
            "metadata": {"source": "github"}
        }
        self.supabase.table("entities").upsert(entity, on_conflict="id").execute()
