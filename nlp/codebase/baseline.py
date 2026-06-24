# nlp/codebase/baseline.py
"""
A simple baseline syncer for GitHub repositories.
It performs a full tree walk and indexes all files in the repository, storing relevant metadata in the database.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict

from github import Github, GithubException
from supabase import Client

logger = logging.getLogger(__name__)


class CodebaseBaselineSync:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.gh = Github(os.getenv("GITHUB_TOKEN"))  # Set GITHUB_TOKEN in .env

    def sync_repository(self, repo_full_name: str) -> bool:
        """Perform full tree walk and index all files."""
        logger.info(f"Starting full baseline sync for {repo_full_name}")

        try:
            repo = self.gh.get_repo(repo_full_name)

            # 1. Ensure repository record
            repo_data = {
                "full_name": repo_full_name,
                "company_id": "default",
                "description": repo.description,
                "language": repo.language,
                "default_branch": repo.default_branch,
                "last_synced_at": datetime.now(timezone.utc).isoformat(),
            }
            self.supabase.table("repositories").upsert(repo_data, on_conflict="full_name").execute()

            # Get repo_id
            repo_res = self.supabase.table("repositories").select("id").eq("full_name", repo_full_name).single().execute()
            repo_id = repo_res.data["id"]

            # 2. Walk tree (non-recursive for MVP)
            contents = repo.get_contents("")
            files_processed = 0

            while contents:
                item = contents.pop(0)

                if item.type == "dir":
                    # Expand directories
                    try:
                        contents.extend(repo.get_contents(item.path))
                    except GithubException:
                        continue
                    continue

                if item.type == "file":
                    await self._index_file(item, repo_id, repo_full_name)
                    files_processed += 1

            logger.info(f"Baseline sync complete: {files_processed} files indexed for {repo_full_name}")
            return True

        except Exception as e:
            logger.error(f"Baseline sync failed for {repo_full_name}: {e}", exc_info=True)
            return False

    async def _index_file(self, gh_file, repo_id: str, repo_full_name: str):
        """Index single file from GitHub content object."""
        file_path = gh_file.path
        file_name = file_path.split("/")[-1]

        file_data = {
            "repository_id": repo_id,
            "file_path": file_path,
            "file_name": file_name,
            "language": self._detect_language(file_path),
            "loc": 0,  # Can enhance later with size or real LOC
            "last_modified_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "github_sha": gh_file.sha,
                "size": gh_file.size,
                "html_url": gh_file.html_url
            }
        }

        self.supabase.table("codebase_files").upsert(
            file_data, 
            on_conflict="repository_id,file_path"
        ).execute()

        logger.info(f"Indexed: {file_path}")

    def _detect_language(self, file_path: str) -> str:
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        mapping = {"go": "Go", "py": "Python", "js": "JavaScript", "ts": "TypeScript", "java": "Java",
                   "cpp": "C++", "c": "C", "rs": "Rust", "rb": "Ruby", "php": "PHP", "swift": "Swift",
                   "kt": "Kotlin", "scala": "Scala", "hs": "Haskell", "lua": "Lua", "pl": "Perl",
                   "sh": "Shell", "bash": "Bash"}
        return mapping.get(ext, "Unknown")
