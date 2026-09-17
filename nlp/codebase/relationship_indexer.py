"""Index deterministic implementation relationships for a repository."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from github import GithubException

from codebase.relationships import ImplementationRelationshipExtractor

logger = logging.getLogger(__name__)


class ImplementationRelationshipIndexer:
    """Fetch indexed source files, extract relationships, and persist graph edges."""

    RELATION_TYPES = {"IMPORTS"}

    def __init__(self, supabase, github_client):
        self.supabase = supabase
        self.github = github_client
        self.extractor = ImplementationRelationshipExtractor()

    def index_repository(self, repo_full_name: str, company_id: str) -> int:
        """Rebuild resolvable implementation relationships for one repository."""
        repo = self.github.get_repo(repo_full_name)
        repository_rows = self._load_repository_rows(repo, company_id)
        inventory = self._load_source_inventory(repo, repository_rows)
        relations = self.extractor.extract(inventory)

        file_entity_ids = {
            row["file_path"]: self._file_entity_id(repo_full_name, company_id, row["file_path"])
            for row in repository_rows
        }
        self._remove_existing_edges(list(file_entity_ids.values()), company_id)

        rows = []
        for relation in relations:
            source_id = file_entity_ids.get(relation.source_path)
            target_id = file_entity_ids.get(relation.target_path)
            if not source_id or not target_id:
                continue
            edge_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"implementation:{relation.relation_type}:{source_id}:{target_id}",
                )
            )
            rows.append(
                {
                    "id": edge_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "type": relation.relation_type,
                    "confidence": relation.confidence,
                    "created_at": self._now(),
                    "company_id": company_id,
                }
            )

        if rows:
            self.supabase.table("edges").upsert(rows, on_conflict="id").execute()

        logger.info(
            "Indexed %d implementation relationships for %s | company=%s",
            len(rows),
            repo_full_name,
            company_id,
        )
        return len(rows)

    def _load_repository_rows(self, repo, company_id: str) -> list[dict[str, Any]]:
        """Load all file records belonging to this tenant's physical repository."""
        rows = (
            self.supabase.table("codebase_files")
            .select("file_path,language,repository_id")
            .eq("company_id", company_id)
            .execute()
        )
        repo_row = (
            self.supabase.table("repositories")
            .select("id")
            .eq("full_name", repo.full_name)
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
        if not repo_row.data:
            return []
        repository_id = repo_row.data[0]["id"]
        return [
            row for row in (rows.data or [])
            if row.get("repository_id") == repository_id and row.get("file_path")
        ]

    def _load_source_inventory(
        self, repo, repository_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Load readable Python/Go source content from repository file records."""

        inventory: list[dict[str, Any]] = []
        for row in repository_rows:
            path = row.get("file_path")
            if not path or row.get("language") not in {"Python", "Go"}:
                continue
            try:
                content = repo.get_contents(path)
                if isinstance(content, list):
                    continue
                text = content.decoded_content.decode("utf-8")
            except (GithubException, UnicodeDecodeError, AttributeError) as exc:
                logger.debug("Skipping unreadable source %s: %s", path, exc)
                continue
            inventory.append({"path": path, "language": row.get("language"), "content": text})

        if any(item["language"] == "Go" for item in inventory):
            for row in repository_rows:
                path = row.get("file_path")
                if not path or not path.endswith("go.mod"):
                    continue
                try:
                    go_mod = repo.get_contents(path)
                    if not isinstance(go_mod, list):
                        inventory.append(
                            {
                                "path": path,
                                "language": "GoModule",
                                "content": go_mod.decoded_content.decode("utf-8"),
                            }
                        )
                except (GithubException, UnicodeDecodeError, AttributeError):
                    continue
        return inventory

    def _remove_existing_edges(self, file_entity_ids: list[str], company_id: str) -> None:
        """Remove only implementation edges owned by this repository's source files."""
        for source_id in file_entity_ids:
            self.supabase.table("edges").delete().eq("source_id", source_id).eq(
                "company_id", company_id
            ).in_("type", list(self.RELATION_TYPES)).execute()

    @staticmethod
    def _file_entity_id(repo_full_name: str, company_id: str, path: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"file:{company_id}:{repo_full_name}:{path}"))

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
