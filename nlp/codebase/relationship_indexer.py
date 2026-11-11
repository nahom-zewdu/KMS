"""Index deterministic implementation relationships for a repository."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from github import GithubException

from codebase.relationships import ImplementationRelationshipExtractor
from ramp.behavioral_evidence_producer import GoBehavioralEvidenceProducer

logger = logging.getLogger(__name__)


class ImplementationRelationshipIndexer:
    """Fetch indexed source files, extract relationships, and persist graph edges."""

    RELATION_TYPES = {"IMPORTS", "ROUTE_HANDLER_OPERATION"}

    def __init__(self, supabase, github_client):
        self.supabase = supabase
        self.github = github_client
        self.extractor = ImplementationRelationshipExtractor()
        self.behavioral_producer = GoBehavioralEvidenceProducer()

    def index_repository(
        self, repo_full_name: str, company_id: str, *, source_revision: str | None = None
    ) -> int:
        """Rebuild resolvable implementation relationships for one repository."""
        repo = self.github.get_repo(repo_full_name)
        if not source_revision:
            raise ValueError("source_revision must be an immutable Git commit SHA")
        repository_rows = self._load_repository_rows(repo, company_id)
        inventory = self._load_source_inventory(repo, repository_rows, ref=source_revision)
        relations = self.extractor.extract(inventory)
        repository_id = next(
            (str(row["repository_id"]) for row in repository_rows if row.get("repository_id")),
            None,
        )
        if not repository_id:
            return 0
        go_inventory = [
            {"path": item["path"], "content": item["content"]}
            for item in inventory if item.get("language") == "Go"
        ]
        behavioral_records = self.behavioral_producer.produce(
            go_inventory,
            repository_id=repository_id,
            source_revision=source_revision,
        )

        file_entity_ids = {
            row["file_path"]: self._file_entity_id(repo_full_name, company_id, row["file_path"])
            for row in repository_rows
        }
        source_entity_ids = list(file_entity_ids.values())

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

        for record in behavioral_records:
            if record.evidence_type != "ROUTE_HANDLER_OPERATION":
                continue
            route, call = record.provenance
            source_id = file_entity_ids.get(route.source_file)
            target_id = file_entity_ids.get(call.source_file)
            if not source_id or not target_id:
                continue
            edge_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"implementation:{record.ref}")
            )
            rows.append(
                {
                    "id": edge_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "type": record.evidence_type,
                    "confidence": 0.8,
                    "metadata": {
                        "evidence_ref": record.ref,
                        "repository_id": repository_id,
                        "source_revision": source_revision,
                        "extractor_id": route.extractor_id,
                        "extractor_version": route.extractor_version,
                        "detail": record.detail,
                        "provenance": [
                            {
                                "repository_id": item.repository_id,
                                "source_revision": item.source_revision,
                                "extractor_id": item.extractor_id,
                                "extractor_version": item.extractor_version,
                                "source_file": item.source_file,
                                "line": item.line,
                                "observation": item.observation,
                                "limitations": list(item.limitations),
                            }
                            for item in record.provenance
                        ],
                    },
                    "created_at": self._now(),
                    "company_id": company_id,
                }
            )

        # One PostgreSQL RPC validates and replaces the full edge set atomically.
        self.supabase.rpc(
            "replace_implementation_edges",
            {
                "p_company_id": company_id,
                "p_source_ids": source_entity_ids,
                "p_edges": rows,
            },
        ).execute()

        logger.info(
            "Indexed %d implementation relationships for %s | company=%s",
            len(rows),
            repo_full_name,
            company_id,
        )
        return len(rows)

    def _load_repository_rows(self, repo, company_id: str) -> list[dict[str, Any]]:
        """Load all file records belonging to this tenant's physical repository."""
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
        rows = (
            self.supabase.table("codebase_files")
            .select("file_path,language,repository_id")
            .eq("repository_id", repository_id)
            .execute()
        )
        return [row for row in (rows.data or []) if row.get("file_path")]

    def _load_source_inventory(
        self, repo, repository_rows: list[dict[str, Any]], *, ref: str
    ) -> list[dict[str, Any]]:
        """Load readable Python/Go source content from repository file records."""

        inventory: list[dict[str, Any]] = []
        for row in repository_rows:
            path = row.get("file_path")
            if not path or row.get("language") not in {"Python", "Go"}:
                continue
            try:
                content = repo.get_contents(path, ref=ref)
                if isinstance(content, list):
                    continue
                text = content.decoded_content.decode("utf-8")
            except (GithubException, UnicodeDecodeError, AttributeError) as exc:
                if row.get("language") == "Go":
                    raise RuntimeError(
                        f"Cannot build complete Go behavioral snapshot: {path}"
                    ) from exc
                logger.debug("Skipping unreadable source %s: %s", path, exc)
                continue
            inventory.append({"path": path, "language": row.get("language"), "content": text})

        if any(item["language"] == "Go" for item in inventory):
            for row in repository_rows:
                path = row.get("file_path")
                if not path or not path.endswith("go.mod"):
                    continue
                try:
                    go_mod = repo.get_contents(path, ref=ref)
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

    @staticmethod
    def _file_entity_id(repo_full_name: str, company_id: str, path: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"file:{company_id}:{repo_full_name}:{path}"))

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
