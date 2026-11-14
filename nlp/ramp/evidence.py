"""Company-scoped evidence extraction for Ramp intelligence.

The extractor owns facts. It does not decide what an engineer should learn.
Ramp candidates consume the normalized evidence produced here.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from supabase import Client

logger = logging.getLogger(__name__)
_LIVE_ISSUE_CACHE: Dict[str, tuple[float, Optional[Dict[str, Any]]]] = {}
_LIVE_ISSUE_CACHE_LOCK = threading.Lock()
_LIVE_ISSUE_CACHE_TTL_SECONDS = 300

from .models import Evidence, ImplementationSurface


class RampEvidenceRetrievalError(RuntimeError):
    """A database read failed while collecting evidence for Ramp generation."""

    def __init__(self, source: str, operation: str, error_type: str):
        self.source = source
        self.operation = operation
        self.error_type = error_type
        super().__init__(
            f"Ramp evidence retrieval failed: source={source}, operation={operation}"
        )


class RampEvidenceStore:
    """Read the existing KMS knowledge model for one company."""

    def __init__(self, supabase: Client):
        self.supabase = supabase

    def implementation_surfaces(self, company_id: str) -> List[ImplementationSurface]:
        """Return indexed files for a company as normalized implementation surfaces."""
        self._require_company_id(company_id)
        repositories = self._repository_records(company_id)
        repository_ids = [str(row["id"]) for row in repositories if row.get("id")]
        if not repository_ids:
            return []
        repository_by_id = {str(row["id"]): row for row in repositories if row.get("id")}
        response = self._retrieve(
            "codebase_files",
            "list implementation surfaces",
            lambda: (
                self.supabase.table("codebase_files")
                .select(
                    "id, repository_id, file_path, module_path, language, file_name, "
                    "last_author, last_commit_sha, importance_score, metadata"
                )
                .in_("repository_id", repository_ids)
                .limit(5000)
                .execute()
            ),
        )

        result: List[ImplementationSurface] = []
        for row in getattr(response, "data", []) or []:
            path = str(row.get("file_path") or "").strip()
            if not path:
                continue
            result.append(
                ImplementationSurface(
                    ref=str(row.get("id") or f"{row.get('repository_id')}:{path}"),
                    path=path,
                    repository_id=row.get("repository_id"),
                    module_path=row.get("module_path"),
                    language=row.get("language"),
                    importance=float(row.get("importance_score") or 0.0),
                    last_author=row.get("last_author"),
                    last_commit_sha=row.get("last_commit_sha"),
                    metadata={
                        **(row.get("metadata") if isinstance(row.get("metadata"), dict) else {}),
                        "repository_full_name": repository_by_id.get(str(row.get("repository_id")), {}).get("full_name"),
                        "repository_default_branch": repository_by_id.get(str(row.get("repository_id")), {}).get("default_branch"),
                    },
                )
            )
        return sorted(result, key=lambda item: (-item.importance, item.path))

    def module_records(self, company_id: str) -> List[Dict[str, Any]]:
        """Return company-scoped module records without interpreting their meaning."""
        self._require_company_id(company_id)
        repository_ids = self._repository_ids(company_id)
        if not repository_ids:
            return []
        response = self._retrieve(
            "codebase_modules",
            "list module records",
            lambda: (
                self.supabase.table("codebase_modules")
                .select(
                    "id, repository_id, module_path, module_name, inferred_type, "
                    "description, importance_score, metadata"
                )
                .in_("repository_id", repository_ids)
                .limit(1000)
                .execute()
            ),
        )
        return [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]

    def _repository_records(self, company_id: str) -> List[Dict[str, Any]]:
        response = self._retrieve(
            "repositories",
            "list company repositories",
            lambda: (
                self.supabase.table("repositories")
                .select("id, full_name, default_branch")
                .eq("company_id", company_id)
                .execute()
            ),
        )
        return [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]

    def _repository_ids(self, company_id: str) -> List[str]:
        return [str(row["id"]) for row in self._repository_records(company_id) if row.get("id")]

    def ownership(self, company_id: str) -> List[Dict[str, Any]]:
        """Return ownership edges available in the existing knowledge graph."""
        self._require_company_id(company_id)
        response = self._retrieve(
            "edges",
            "list ownership relationships",
            lambda: (
                self.supabase.table("edges")
                .select("source_id, target_id, type, metadata, confidence")
                .eq("company_id", company_id)
                .eq("type", "OWNS")
                .limit(5000)
                .execute()
            ),
        )
        return [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]

    def implementation_relationships(self, company_id: str) -> List[Evidence]:
        """Return graph relationships whose endpoints resolve to FILE entities.

        PART_OF and OWNS are intentionally excluded: they establish containment
        or ownership, not behavioral control/data flow between implementation surfaces.
        """
        self._require_company_id(company_id)
        entities = self._retrieve(
            "entities",
            "list file entities",
            lambda: (
                self.supabase.table("entities")
                .select("id, metadata")
                .eq("company_id", company_id)
                .eq("type", "FILE")
                .limit(10000)
                .execute()
            ),
        )
        edges = self._retrieve(
            "edges",
            "list implementation relationships",
            lambda: (
                self.supabase.table("edges")
                .select("id, source_id, target_id, type, confidence, company_id, metadata")
                .eq("company_id", company_id)
                .limit(20000)
                .execute()
            ),
        )

        file_paths: Dict[str, str] = {}
        for row in getattr(entities, "data", []) or []:
            if not isinstance(row, dict):
                continue
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            path = str(metadata.get("file_path") or "").strip()
            if path and row.get("id"):
                file_paths[str(row["id"])] = path

        repository_ids = self._repository_ids(company_id)
        file_rows = self._retrieve(
            "codebase_files",
            "validate behavioral evidence repository membership",
            lambda: (
                self.supabase.table("codebase_files")
                .select("repository_id, file_path")
                .in_("repository_id", repository_ids)
                .limit(10000)
                .execute()
            ),
        )
        path_repository_ids: Dict[str, set[str]] = {}
        for row in getattr(file_rows, "data", []) or []:
            if isinstance(row, dict) and row.get("file_path") and row.get("repository_id"):
                path_repository_ids.setdefault(str(row["file_path"]), set()).add(
                    str(row["repository_id"])
                )

        result: List[Evidence] = []
        for edge in getattr(edges, "data", []) or []:
            if not isinstance(edge, dict):
                continue
            relation_type = str(edge.get("type") or "").upper()
            source_path = file_paths.get(str(edge.get("source_id") or ""))
            target_path = file_paths.get(str(edge.get("target_id") or ""))
            metadata = edge.get("metadata") if isinstance(edge.get("metadata"), dict) else {}
            provenance_items = metadata.get("provenance")
            if (
                relation_type != "ROUTE_HANDLER_OPERATION"
                or not source_path
                or not target_path
                or str(edge.get("company_id") or "") != company_id
                or not isinstance(provenance_items, list)
                or len(provenance_items) != 2
                or not all(isinstance(item, dict) for item in provenance_items)
                or str(metadata.get("repository_id") or "") not in path_repository_ids.get(source_path, set())
                or str(metadata.get("repository_id") or "") not in path_repository_ids.get(target_path, set())
            ):
                continue
            provenance = {
                "repository_id": metadata.get("repository_id"),
                "source_revision": metadata.get("source_revision"),
                "extractor_id": metadata.get("extractor_id"),
                "extractor_version": metadata.get("extractor_version"),
                "source_file": provenance_items[0].get("source_file"),
                "line": provenance_items[0].get("line"),
                "observation": "derived",
                "call_source_file": provenance_items[1].get("source_file"),
                "call_line": provenance_items[1].get("line"),
                "call_observation": provenance_items[1].get("observation"),
                "limitations": provenance_items[0].get("limitations", []),
            }
            if (
                provenance.get("repository_id") is None
                or provenance.get("source_revision") is None
                or provenance.get("extractor_id") is None
                or provenance.get("extractor_version") is None
                or provenance.get("source_file") != source_path
                or provenance.get("call_source_file") != target_path
                or provenance.get("observation") != "derived"
                or provenance.get("call_observation") != "direct"
                or not isinstance(provenance.get("line"), int)
                or provenance.get("line") < 1
                or not isinstance(provenance.get("call_line"), int)
                or provenance.get("call_line") < 1
                or len(str(provenance.get("source_revision") or "")) != 40
            ):
                continue
            try:
                confidence = float(edge.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            strength = "direct" if confidence >= 0.8 else "derived" if confidence >= 0.6 else "inferred"
            result.append(
                Evidence(
                    ref=f"edge:{edge.get('id')}",
                    source="edges",
                    kind="implementation_relation",
                    strength=strength,
                    detail=str(metadata.get("detail") or f"{source_path} --{relation_type}--> {target_path}"),
                    repository_id=str(provenance["repository_id"]),
                    metadata={
                        "source_ref": source_path,
                        "target_ref": target_path,
                        "relation_type": relation_type,
                        "confidence": confidence,
                        "provenance": provenance,
                    },
                )
            )
        return result

    def github_history(self, company_id: str) -> List[Dict[str, Any]]:
        """Return recent GitHub-derived raw knowledge for corroboration."""
        self._require_company_id(company_id)
        response = self._retrieve(
            "raw_data",
            "list GitHub history",
            lambda: (
                self.supabase.table("raw_data")
                .select("record_id, event_id, source, content, created_at")
                .eq("company_id", company_id)
                .eq("source", "github")
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            ),
        )
        return [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]

    def contribution_issues(self, company_id: str) -> List[Dict[str, Any]]:
        """Return conservative contribution leads from tenant-scoped GitHub issue events.

        Only live-open, unassigned issues explicitly marked good-first-issue/help-wanted,
        with multiple acceptance checks and indexed source paths, are returned.
        When GitHub cannot be reached, a recent indexed snapshot may be returned as
        unverified; consumers must keep that status visible to the user.
        """
        self._require_company_id(company_id)
        repositories = self._repository_records(company_id)
        repo_by_name = {
            str(row.get("full_name") or "").lower(): row
            for row in repositories if row.get("id") and row.get("full_name")
        }
        if not repo_by_name:
            return []
        # Page through a bounded recent history. A single Supabase response can
        # be capped by the project's max-row setting, hiding older backfilled issues.
        event_rows: List[Dict[str, Any]] = []
        page_size = 1000
        max_event_rows = 5000
        for offset in range(0, max_event_rows, page_size):
            response = self._retrieve(
                "events",
                "list company GitHub issue events",
                lambda offset=offset: (
                    self.supabase.table("events")
                    .select("delivery_id, company_id, event_type, payload, created_at")
                    .eq("company_id", company_id)
                    .eq("source", "github")
                    .eq("event_type", "issues")
                    .order("created_at", desc=True)
                    .range(offset, offset + page_size - 1)
                    .execute()
                ),
            )
            page = getattr(response, "data", []) or []
            event_rows.extend(row for row in page if isinstance(row, dict))
            if len(page) < page_size:
                break
        files_response = self._retrieve(
            "codebase_files",
            "list files for contribution issue matching",
            lambda: (
                self.supabase.table("codebase_files")
                .select("repository_id, file_path")
                .in_("repository_id", [str(row["id"]) for row in repo_by_name.values()])
                .limit(10000)
                .execute()
            ),
        )
        files_by_repo: Dict[str, set[str]] = {}
        for row in getattr(files_response, "data", []) or []:
            if isinstance(row, dict) and row.get("repository_id") and row.get("file_path"):
                files_by_repo.setdefault(str(row["repository_id"]), set()).add(str(row["file_path"]))

        results: List[Dict[str, Any]] = []
        path_pattern = re.compile(r"(?<![A-Za-z0-9_.-])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9]+")
        seen_issue_keys = set()
        live_checks_remaining = 50
        for row in event_rows:
            if str(row.get("company_id") or "") != company_id:
                continue
            payload = row.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    continue
            if not isinstance(payload, dict):
                continue
            repo_name = str(payload.get("repo") or "").lower()
            repository = repo_by_name.get(repo_name)
            issue = payload.get("issue")
            if not repository or not isinstance(issue, dict):
                continue
            issue_key = (repo_name, str(issue.get("number") or ""))
            if not issue_key[1] or issue_key in seen_issue_keys:
                continue
            # The newest webhook snapshot wins, even when it is closed or assigned;
            # never resurrect an older open/unassigned event for the same issue.
            seen_issue_keys.add(issue_key)
            # Filter indexed snapshots before spending GitHub API quota. Live
            # verification is capped per plan generation to bound latency/rate use.
            if str(issue.get("state") or "").lower() != "open" or issue.get("assignee"):
                continue
            snapshot_labels = issue.get("labels") if isinstance(issue.get("labels"), list) else []
            snapshot_label_names = {
                str(label.get("name") if isinstance(label, dict) else label).strip().lower()
                for label in snapshot_labels
            }
            eligible_labels = {"good first issue", "good-first-issue", "help wanted", "help-wanted"}
            if not snapshot_label_names.intersection(eligible_labels):
                continue
            snapshot_body = str(issue.get("body") or "")
            snapshot_checks = [
                line.strip() for line in snapshot_body.splitlines()
                if re.match(r"^\s*(?:[-*+]\s+\[[ xX]\]|\d+[.)]\s+)", line)
            ]
            if len(snapshot_checks) < 2:
                continue
            repo_id = str(repository["id"])
            known_paths = files_by_repo.get(repo_id, set())
            snapshot_paths = {
                match.group(0).rstrip(".,:;)")
                for match in path_pattern.finditer(snapshot_body)
            } & known_paths
            if not snapshot_paths:
                continue

            if live_checks_remaining > 0:
                live_issue, live_status = self._live_issue_snapshot(
                    str(repository.get("full_name") or ""),
                    str(issue.get("number") or ""),
                )
                live_checks_remaining -= 1
            else:
                live_issue, live_status = None, "unverified"
            if live_status == "not_found":
                continue
            current_issue = {**issue, **(live_issue or {})}
            if str(current_issue.get("state") or "").lower() != "open" or current_issue.get("assignee"):
                continue
            labels = current_issue.get("labels") if isinstance(current_issue.get("labels"), list) else []
            label_names = {
                str(label.get("name") if isinstance(label, dict) else label).strip().lower()
                for label in labels
            }
            if not label_names.intersection(eligible_labels):
                continue
            body = str(current_issue.get("body") or "")
            checks = [
                line.strip() for line in body.splitlines()
                if re.match(r"^\s*(?:[-*+]\s+\[[ xX]\]|\d+[.)]\s+)", line)
            ]
            if len(checks) < 2:
                continue
            referenced_paths = sorted({
                match.group(0).rstrip(".,:;)")
                for match in path_pattern.finditer(body)
            } & known_paths)
            if not referenced_paths:
                continue
            results.append({
                "ref": f"github-issue:{row.get('delivery_id')}:{issue.get('number')}",
                "delivery_id": row.get("delivery_id"),
                "repository_id": repo_id,
                "repository_full_name": repository.get("full_name"),
                "default_branch": repository.get("default_branch") or "HEAD",
                "number": current_issue.get("number"),
                "title": str(current_issue.get("title") or "").strip(),
                "body": body,
                "url": current_issue.get("html_url"),
                "labels": sorted(label_names),
                "acceptance_checks": checks,
                "file_paths": referenced_paths,
                "created_at": row.get("created_at"),
                "live_status": live_status,
                "live_verified_at": live_issue.get("_verified_at") if live_issue else None,
            })
        return sorted(results, key=lambda item: (str(item.get("repository_full_name")), int(item.get("number") or 0)))

    @staticmethod
    def _live_issue_snapshot(
        repository_full_name: str,
        issue_number: str,
    ) -> tuple[Optional[Dict[str, Any]], str]:
        """Fetch and briefly cache GitHub's current issue state.

        Returns (snapshot, status): verified, unverified, or not_found. Failures
        deliberately fall back to the indexed snapshot but never masquerade as
        a successful live verification.
        """
        cache_key = f"{repository_full_name.lower()}#{issue_number}"
        now = time.monotonic()
        with _LIVE_ISSUE_CACHE_LOCK:
            cached = _LIVE_ISSUE_CACHE.get(cache_key)
            if cached and cached[0] > now:
                return cached[1], "verified" if cached[1] is not None else "not_found"

        token = os.getenv("GITHUB_API_TOKEN", "").strip()
        if not token:
            return None, "unverified"
        url = (
            "https://api.github.com/repos/"
            f"{quote(repository_full_name, safe='/')}/issues/{quote(issue_number, safe='')}"
        )
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "KMS-Ramp",
            },
        )
        try:
            with urlopen(request, timeout=4) as response:
                payload = json.loads(response.read(256_000).decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("pull_request"):
                return None, "not_found"
            payload["_verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with _LIVE_ISSUE_CACHE_LOCK:
                _LIVE_ISSUE_CACHE[cache_key] = (
                    time.monotonic() + _LIVE_ISSUE_CACHE_TTL_SECONDS,
                    payload,
                )
            return payload, "verified"
        except HTTPError as exc:
            if exc.code == 404:
                with _LIVE_ISSUE_CACHE_LOCK:
                    _LIVE_ISSUE_CACHE[cache_key] = (
                        time.monotonic() + _LIVE_ISSUE_CACHE_TTL_SECONDS,
                        None,
                    )
                return None, "not_found"
            logger.warning(
                "GitHub issue verification unavailable: repo=%s issue=%s status=%s",
                repository_full_name,
                issue_number,
                exc.code,
            )
            return None, "unverified"
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            logger.warning(
                "GitHub issue verification unavailable: repo=%s issue=%s error=%s",
                repository_full_name,
                issue_number,
                type(exc).__name__,
            )
            return None, "unverified"

    @staticmethod
    def _require_company_id(company_id: str) -> None:
        if not company_id or not company_id.strip() or company_id.strip().lower() == "default":
            raise ValueError("A real company_id is required for Ramp evidence")

    @staticmethod
    def _retrieve(source: str, operation: str, request: Callable[[], Any]) -> Any:
        try:
            return request()
        except Exception as exc:
            raise RampEvidenceRetrievalError(
                source=source,
                operation=operation,
                error_type=type(exc).__name__,
            ) from None

    def evidence_for_surface(self, surface: ImplementationSurface) -> Evidence:
        """Convert one indexed implementation surface into a traceable evidence item."""
        return Evidence(
            ref=surface.path,
            source="codebase_files",
            kind="implementation_surface",
            strength="direct",
            detail="Company-scoped codebase index record.",
            repository_id=surface.repository_id,
            module_path=surface.module_path,
            metadata={
                "importance_score": surface.importance,
                "language": surface.language,
                "last_author": surface.last_author,
                "last_commit_sha": surface.last_commit_sha,
            },
        )
