# nlp/codebase/baseline.py
"""
Full baseline syncer for GitHub repositories.
This module performs a complete traversal of the repository tree, indexing files and modules.
It creates REPOSITORY entities, FILE entities, and PART_OF relationships in the knowledge graph,
and populates the codebase_files and codebase_modules tables in Supabase.
The sync is designed to be idempotent and can be re-run safely.
The main entry point is the `sync_repository` method, which takes a repository full name
Creates REPOSITORY entity + codebase_files + PART_OF edges safely.
"""

import logging
import os
import threading
from datetime import datetime, timezone
import uuid
from typing import Dict

from github import Github, GithubException
from supabase import Client

from codebase.relationship_indexer import ImplementationRelationshipIndexer
from codebase.symbol_indexer import CodeSymbolIndexer

logger = logging.getLogger(__name__)


class CodebaseBaselineSync:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.gh = Github(os.getenv("GITHUB_API_TOKEN"))
        self.relationship_indexer = ImplementationRelationshipIndexer(self.supabase, self.gh)
        self.symbol_indexer = CodeSymbolIndexer(self.supabase)

    def _set_sync_state(self, repo_full_name: str, company_id: str, **fields) -> None:
        """Persist baseline lifecycle state for the company-owned repository."""
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.supabase.table("repositories").update(fields).eq(
            "full_name", repo_full_name
        ).eq("company_id", company_id).execute()

    def sync_repository(self, repo_full_name: str, company_id: str) -> bool:
        """Index one immutable Git revision under a database-backed repository lease."""
        if not company_id or company_id.strip().lower() == "default":
            raise ValueError("company_id must resolve to a real company")

        run_id = str(uuid.uuid4())
        lease_stop = threading.Event()
        lease_lost = threading.Event()
        lease_thread = None
        lease_claimed = False
        snapshot_id = None

        def ensure_lease() -> None:
            if lease_lost.is_set():
                raise RuntimeError("baseline lease was lost; refusing further repository writes")

        def renew_lease() -> None:
            while not lease_stop.wait(30):
                try:
                    renewed = self.supabase.rpc(
                        "renew_repository_baseline_lease",
                        {
                            "p_full_name": repo_full_name,
                            "p_company_id": company_id,
                            "p_run_id": run_id,
                            "p_lease_seconds": 180,
                        },
                    ).execute()
                    if renewed.data is not True:
                        lease_lost.set()
                        logger.error(
                            "Baseline lease renewal rejected | repo=%s | company=%s | run=%s",
                            repo_full_name, company_id, run_id,
                        )
                        return
                except Exception:
                    lease_lost.set()
                    logger.exception(
                        "Baseline lease renewal failed | repo=%s | company=%s | run=%s",
                        repo_full_name, company_id, run_id,
                    )
                    return

        logger.info(
            "Starting full baseline sync for %s | company=%s | run=%s",
            repo_full_name, company_id, run_id,
        )
        try:
            # Resolve a fixed Git snapshot before attempting to claim the repository.
            repo = self.gh.get_repo(repo_full_name)
            source_revision = repo.get_branch(repo.default_branch).commit.sha
            claim = self.supabase.rpc(
                "claim_repository_baseline",
                {
                    "p_full_name": repo_full_name,
                    "p_company_id": company_id,
                    "p_source_revision": source_revision,
                    "p_run_id": run_id,
                    "p_lease_seconds": 180,
                },
            ).execute()
            claim_status = claim.data
            if isinstance(claim_status, list) and claim_status:
                claim_status = claim_status[0]
            if isinstance(claim_status, dict):
                claim_status = claim_status.get("claim_repository_baseline")
            if claim_status == "ready":
                logger.info(
                    "Baseline already ready at revision %s; skipping duplicate sync | repo=%s",
                    source_revision, repo_full_name,
                )
                return True
            if claim_status != "claimed":
                logger.info(
                    "Baseline claim unavailable (%s); leaving job retryable | repo=%s | run=%s",
                    claim_status, repo_full_name, run_id,
                )
                return False

            lease_claimed = True
            lease_thread = threading.Thread(
                target=renew_lease,
                name=f"baseline-lease-{run_id[:8]}",
                daemon=True,
            )
            lease_thread.start()
            started_at = datetime.now(timezone.utc).isoformat()
            now = started_at
            ensure_lease()

            # 1. REPOSITORY entity (tenant-scoped id)
            repo_entity_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"repo:{company_id}:{repo_full_name}")
            )
            self.supabase.table("entities").upsert(
                {
                    "id": repo_entity_id,
                    "type": "REPOSITORY",
                    "name": repo_full_name,
                    "company_id": company_id,
                    "metadata": {
                        "description": repo.description or "",
                        "language": repo.language,
                        "default_branch": repo.default_branch,
                        "company_id": company_id,
                    },
                    "created_at": now,
                },
                on_conflict="id",
            ).execute()

            # 2. repositories table
            existing = (
                self.supabase.table("repositories")
                .select("id")
                .eq("full_name", repo_full_name)
                .eq("company_id", company_id)
                .limit(1)
                .execute()
            )
            if existing.data:
                physical_repo_id = existing.data[0]["id"]
                self.supabase.table("repositories").update(
                    {
                        "description": repo.description or "",
                        "language": repo.language,
                        "default_branch": repo.default_branch,
                        "updated_at": now,
                    }
                ).eq("id", physical_repo_id).eq("company_id", company_id).execute()
            else:
                physical_repo_id = str(uuid.uuid4())
                self.supabase.table("repositories").insert(
                    {
                        "id": physical_repo_id,
                        "full_name": repo_full_name,
                        "company_id": company_id,
                        "description": repo.description or "",
                        "language": repo.language,
                        "default_branch": repo.default_branch,
                        "baseline_status": "indexing",
                        "baseline_started_at": now,
                        "updated_at": now,
                    }
                ).execute()

            snapshot_response = self.supabase.rpc(
                "create_repository_snapshot",
                {
                    "p_repository_id": physical_repo_id,
                    "p_company_id": company_id,
                    "p_run_id": run_id,
                    "p_source_revision": source_revision,
                },
            ).execute()
            snapshot_id = snapshot_response.data
            if isinstance(snapshot_id, list) and snapshot_id:
                snapshot_id = snapshot_id[0]
            if isinstance(snapshot_id, dict):
                snapshot_id = snapshot_id.get("create_repository_snapshot")
            if not snapshot_id:
                raise RuntimeError("repository snapshot creation returned no snapshot ID")

            # Author map from recent commits (most recent author wins per file).
            # Pin history lookup to the same immutable revision as the inventory.
            author_map = self._build_author_map(repo, max_commits=200, sha=source_revision)
            logger.info("Author map: %d files with last_author", len(author_map))

            contents = repo.get_contents("", ref=source_revision)
            files_processed = 0
            symbol_metrics = {
                "files_seen": 0,
                "files_indexed": 0,
                "files_with_syntax_errors": 0,
                "files_unsupported": 0,
                "files_oversized": 0,
                "files_unavailable": 0,
                "symbols_persisted": 0,
                "source_bytes_skipped": 0,
            }
            module_map: Dict[str, int] = {}
            live_paths: list[str] = []

            while contents:
                ensure_lease()
                item = contents.pop(0)
                if item.type == "dir":
                    try:
                        contents.extend(repo.get_contents(item.path, ref=source_revision))
                        module_map[item.path] = module_map.get(item.path, 0) + 1
                    except GithubException as exc:
                        # Never reconcile from a partial tree: a failed directory
                        # traversal must not be interpreted as deleted files.
                        raise RuntimeError(
                            f"Cannot complete repository tree traversal at {item.path}"
                        ) from exc
                    continue
                if item.type == "file":
                    file_symbol_metrics = self._index_file(
                        item,
                        repo_entity_id,
                        physical_repo_id,
                        repo_full_name,
                        company_id,
                        last_author=author_map.get(item.path),
                        snapshot_id=snapshot_id,
                        source_revision=source_revision,
                    )
                    files_processed += 1
                    for metric, value in file_symbol_metrics.items():
                        symbol_metrics[metric] += value
                    live_paths.append(item.path)

            # Seed the issue history from GitHub so newly connected repositories
            # have contribution candidates even when issues predate webhook setup.
            try:
                issue_count = self._backfill_issue_events(repo, repo_full_name, company_id)
                logger.info(
                    "GitHub issue backfill complete: %d issue snapshots | repo=%s",
                    issue_count,
                    repo_full_name,
                )
            except Exception:
                # Issue discovery is an enhancement to baseline indexing; a GitHub
                # issues API outage must not invalidate a successfully indexed codebase.
                logger.warning(
                    "GitHub issue backfill failed; codebase baseline will remain usable | repo=%s",
                    repo_full_name,
                    exc_info=True,
                )

            # Snapshot rows are staged independently. Do not reconcile or mutate
            # the currently published inventory before the new snapshot is ready.
            ensure_lease()
            for mod_path, file_count in module_map.items():
                ensure_lease()
                self._create_module(
                    mod_path, physical_repo_id, file_count, company_id, snapshot_id=snapshot_id
                )

            # Relationship extraction uses the same immutable snapshot as file indexing.
            ensure_lease()
            relationship_count = self.relationship_indexer.index_repository(
                repo_full_name, company_id, source_revision=source_revision,
                snapshot_id=snapshot_id,
            )
            logger.info(
                "Implementation relationship indexing complete: %d relationships",
                relationship_count,
            )

            ensure_lease()
            self.supabase.table("repository_snapshots").update({
                "symbol_count": symbol_metrics["symbols_persisted"],
                "symbol_validation": symbol_metrics,
            }).eq("id", snapshot_id).eq("status", "building").execute()
            logger.info("Code symbol indexing complete: %s", symbol_metrics)

            ensure_lease()
            completed_at = datetime.now(timezone.utc).isoformat()
            completion = self.supabase.rpc(
                "publish_repository_snapshot",
                {
                    "p_snapshot_id": snapshot_id,
                    "p_run_id": run_id,
                    "p_file_count": files_processed,
                    "p_module_count": len(module_map),
                    "p_relationship_count": relationship_count,
                    "p_completed_at": completed_at,
                },
            ).execute()
            if completion.data is not True:
                raise RuntimeError(
                    "snapshot publication rejected because this run no longer owns the repository lease"
                )
            lease_claimed = False
            logger.info(
                f"Baseline sync complete: {files_processed} files, "
                f"{len(module_map)} modules | company={company_id}"
                f"{len(author_map)} authors | repo={repo_full_name}"
            )
            return True
        except Exception as e:
            logger.error("Baseline sync failed for %s: %s", repo_full_name, e, exc_info=True)
            return False
        finally:
            lease_stop.set()
            if lease_thread is not None:
                lease_thread.join(timeout=5)
            if lease_claimed:
                try:
                    if snapshot_id:
                        self.supabase.rpc(
                            "fail_repository_snapshot",
                            {
                                "p_snapshot_id": snapshot_id,
                                "p_run_id": run_id,
                                "p_error": "Baseline indexing failed. Check worker logs.",
                            },
                        ).execute()
                    else:
                        self.supabase.rpc(
                            "fail_repository_baseline",
                            {
                                "p_full_name": repo_full_name,
                                "p_company_id": company_id,
                                "p_run_id": run_id,
                                "p_error": "Baseline indexing failed. Check worker logs.",
                            },
                        ).execute()
                except Exception:
                    logger.exception("Could not persist failed baseline state for %s", repo_full_name)

    def _backfill_issue_events(
        self,
        repo,
        repo_full_name: str,
        company_id: str,
        max_issues: int = 2000,
        batch_size: int = 100,
    ) -> int:
        """Persist a bounded, idempotent snapshot history of GitHub issues.

        Event created_at is the issue's GitHub updated_at timestamp, not import time.
        This lets newer webhook deliveries win over older backfill snapshots when
        Ramp resolves the latest state for an issue.
        """
        if not company_id or not company_id.strip() or company_id.strip().lower() == "default":
            raise ValueError("company_id must resolve to a real company")
        if max_issues < 1 or batch_size < 1:
            raise ValueError("max_issues and batch_size must be positive")

        batch = []
        snapshots_written = 0
        scanned_items = 0
        issues = repo.get_issues(state="all", sort="updated", direction="desc")
        for issue in issues:
            if scanned_items >= max_issues:
                break
            scanned_items += 1
            # GitHub's issues endpoint also returns pull requests.
            if getattr(issue, "pull_request", None):
                continue
            number = getattr(issue, "number", None)
            updated_at = getattr(issue, "updated_at", None) or getattr(issue, "created_at", None)
            if number is None or updated_at is None:
                continue

            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            else:
                updated_at = updated_at.astimezone(timezone.utc)
            updated_at_text = updated_at.isoformat()
            body = str(getattr(issue, "body", None) or "")
            labels = []
            for label in getattr(issue, "labels", []) or []:
                name = getattr(label, "name", None)
                if name and str(name).strip():
                    labels.append(str(name).strip())
                if len(labels) >= 20:
                    break
            assignee = getattr(issue, "assignee", None)
            assignee_login = getattr(assignee, "login", None) if assignee else None
            issue_snapshot = {
                "number": number,
                "title": str(getattr(issue, "title", None) or ""),
                "body": body[:10000],
                "state": str(getattr(issue, "state", "") or ""),
                "html_url": str(getattr(issue, "html_url", "") or ""),
                "created_at": (
                    getattr(issue, "created_at").replace(tzinfo=timezone.utc).isoformat()
                    if getattr(issue, "created_at").tzinfo is None
                    else getattr(issue, "created_at").astimezone(timezone.utc).isoformat()
                ) if getattr(issue, "created_at", None) else None,
                "updated_at": updated_at_text,
                "labels": labels,
                "assignee": str(assignee_login) if assignee_login else "",
            }
            delivery_id = (
                f"backfill:github-issue:{company_id}:{repo_full_name}:{number}:{updated_at_text}"
            )
            event_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, delivery_id)
            )
            batch.append({
                "id": event_id,
                "company_id": company_id,
                "source": "github",
                "event_type": "issues",
                "payload": {
                    "repo": repo_full_name,
                    "sender": "baseline-backfill",
                    "event_type": "issues",
                    "action": "backfill",
                    "issue": issue_snapshot,
                },
                "delivery_id": delivery_id,
                "processed": True,
                "truncated": len(body) > 10000,
                "created_at": updated_at_text,
            })
            snapshots_written += 1
            if len(batch) >= batch_size:
                self._upsert_issue_event_batch(batch)
                batch = []

        if batch:
            self._upsert_issue_event_batch(batch)
        return snapshots_written

    def _upsert_issue_event_batch(self, events) -> None:
        """Idempotently insert historical issue snapshots without enqueueing workers."""
        self.supabase.table("events").upsert(
            events,
            on_conflict="delivery_id",
            ignore_duplicates=True,
        ).execute()

    def _build_author_map(
        self, repo, max_commits: int = 200, sha: str | None = None
    ) -> Dict[str, str]:
        """
        Walk recent commits (newest first). First time we see a file path wins = last author.
        One pass; avoids per-file commit API calls.
        """
        author_map: Dict[str, str] = {}
        try:
            for i, commit in enumerate(repo.get_commits(sha=sha) if sha else repo.get_commits()):
                if i >= max_commits:
                    break
                try:
                    author = None
                    if commit.author and getattr(commit.author, "login", None):
                        author = commit.author.login
                    elif commit.commit and commit.commit.author:
                        author = commit.commit.author.name
                    if not author:
                        continue
                    author = str(author).strip()
                    for f in commit.files or []:
                        path = getattr(f, "filename", None)
                        if path and path not in author_map:
                            author_map[path] = author
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Failed building author map: %s", e)
        return author_map

    def _index_file(
        self, gh_file, repo_entity_id: str, physical_repo_id: str,
        repo_full_name: str, company_id: str, last_author: str | None = None,
        snapshot_id: str | None = None, source_revision: str | None = None,
    ):
        """Index file metadata, graph ownership, and bounded source declarations."""
        file_path = gh_file.path
        file_name = file_path.split("/")[-1]
        module_path = "/".join(file_path.split("/")[:-1]) if "/" in file_path else ""
        now = datetime.now(timezone.utc).isoformat()
        symbol_metrics = {
            "files_seen": 0,
            "files_indexed": 0,
            "files_with_syntax_errors": 0,
            "files_unsupported": 0,
            "files_oversized": 0,
            "files_unavailable": 0,
            "symbols_persisted": 0,
            "source_bytes_skipped": 0,
        }

        file_entity_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"file:{company_id}:{repo_full_name}:{file_path}")
        )

        self.supabase.table("entities").upsert(
            {
                "id": file_entity_id,
                "type": "FILE",
                "name": file_name,
                "company_id": company_id,
                "metadata": {
                    "file_path": file_path,
                    "module_path": module_path,
                    "language": self._detect_language(file_path),
                    "company_id": company_id,
                    "repository_id": physical_repo_id,
                    "repository_full_name": repo_full_name,
                },
                "created_at": now,
            },
            on_conflict="id",
        ).execute()

        self.supabase.table("codebase_files").upsert(
            {
                "repository_id": physical_repo_id,
                "file_path": file_path,
                "file_name": file_name,
                "module_path": module_path,
                "language": self._detect_language(file_path),
                "last_modified_at": now,
                "last_commit_sha": source_revision,
                "last_author": last_author,
                "snapshot_id": snapshot_id,
                "metadata": {
                    "company_id": company_id,
                    "source_revision": source_revision,
                    "blob_sha": gh_file.sha,
                },
            },
            on_conflict="repository_id,file_path,snapshot_id",
        ).execute()

        # Parse only explicitly supported source extensions. Unsupported and
        # oversized files are recorded as coverage gaps, never guessed.
        from codebase.symbols import CodeSymbolExtractor

        language = CodeSymbolExtractor._language_for_path(file_path)
        symbol_indexer = getattr(self, "symbol_indexer", None)
        if language is not None and symbol_indexer is not None:
            symbol_metrics["files_seen"] = 1
            source_size = getattr(gh_file, "size", None)
            if source_size is not None and source_size > self.symbol_indexer.max_source_bytes:
                symbol_metrics["files_oversized"] = 1
                symbol_metrics["source_bytes_skipped"] = int(source_size)
            else:
                try:
                    decoded = getattr(gh_file, "decoded_content", None)
                    if decoded is None:
                        symbol_metrics["files_unavailable"] = 1
                    else:
                        result = symbol_indexer.index_file(
                            repository_id=physical_repo_id,
                            snapshot_id=snapshot_id,
                            company_id=company_id,
                            file_path=file_path,
                            source=decoded.decode("utf-8"),
                            source_revision=source_revision,
                            language=language,
                        )
                        if result["status"] == "indexed":
                            symbol_metrics["files_indexed"] = 1
                        elif result["status"] == "syntax_error":
                            symbol_metrics["files_indexed"] = 1
                            symbol_metrics["files_with_syntax_errors"] = 1
                        elif result["status"] == "oversized":
                            symbol_metrics["files_oversized"] = 1
                            symbol_metrics["source_bytes_skipped"] = result["source_bytes"]
                        else:
                            symbol_metrics["files_unsupported"] = 1
                        symbol_metrics["symbols_persisted"] = result["symbols_persisted"]
                except UnicodeDecodeError as exc:
                    raise RuntimeError(
                        f"Cannot decode supported source file for symbol indexing: {file_path}"
                    ) from exc

        edge_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"partof:{snapshot_id}:{file_entity_id}:{repo_entity_id}")
        )
        self.supabase.table("edges").upsert(
            {
                "id": edge_id,
                "source_id": file_entity_id,
                "target_id": repo_entity_id,
                "type": "PART_OF",
                "confidence": 1.0,
                "created_at": now,
                "company_id": company_id,
                "snapshot_id": snapshot_id,
            },
            on_conflict="id",
        ).execute()

        if last_author:
            self._upsert_owns(
                last_author, file_entity_id, company_id, now, snapshot_id=snapshot_id
            )

        return symbol_metrics

    def _upsert_owns(
        self, author: str, file_entity_id: str, company_id: str, now: str,
        snapshot_id: str | None = None,
    ):
        """PERSON + OWNS edge (same id scheme as analyzer)."""
        author_norm = str(author).strip().lower()
        if not author_norm:
            return
        person_entity_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"person:{company_id}:{author_norm}")
        )
        self.supabase.table("entities").upsert(
            {
                "id": person_entity_id,
                "type": "PERSON",
                "name": author_norm,
                "company_id": company_id,
                "metadata": {"source": "github_baseline", "company_id": company_id},
                "created_at": now,
            },
            on_conflict="id",
        ).execute()

        owns_edge_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"owns:{snapshot_id}:{person_entity_id}:{file_entity_id}")
        )
        self.supabase.table("edges").upsert(
            {
                "id": owns_edge_id,
                "source_id": person_entity_id,
                "target_id": file_entity_id,
                "type": "OWNS",
                "confidence": 0.8,
                "created_at": now,
                "company_id": company_id,
                "snapshot_id": snapshot_id,
            },
            on_conflict="id",
        ).execute()

    def _create_module(
        self, module_path: str, repo_id: str, file_count: int,
        company_id: str, snapshot_id: str | None = None,
    ):
        """Create/update module with computed importance."""
        module_name = module_path.split("/")[-1] if module_path else "root"
        importance = min(1.0, (file_count / 20.0) + 0.3)

        self.supabase.table("codebase_modules").upsert({
            "repository_id": repo_id,
            "module_path": module_path,
            "module_name": module_name,
            "inferred_type": self._infer_module_type(module_path),
            "description": f"Module containing {file_count} files",
            "importance_score": round(importance, 2),
            "metadata": {"file_count": file_count, "company_id": company_id},
            "snapshot_id": snapshot_id,
        }, on_conflict="repository_id,module_path,snapshot_id").execute()

    def _create_part_of_edge(self, repo_id: str, file_path: str, company_id: str):
        """Create deterministic PART_OF edge using UUID."""
        edge_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"partof:{repo_id}:{file_path}"))
        file_entity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"file:{repo_id}:{file_path}"))

        self.supabase.table("edges").upsert({
            "id": edge_id,
            "source_id": file_entity_id,
            "target_id": repo_id,
            "type": "PART_OF",
            "confidence": 1.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "company_id": company_id,
        }, on_conflict="id").execute()

    def _infer_module_type(self, module_path: str) -> str:
        lower = module_path.lower()
        if any(k in lower for k in ["api", "handlers", "routes"]): return "api"
        if any(k in lower for k in ["nlp", "engine", "worker"]): return "core"
        if any(k in lower for k in ["utils", "common", "helper"]): return "utils"
        return "feature"

    def _detect_language(self, file_path: str) -> str:
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        mapping = {"go": "Go", "py": "Python", "js": "JavaScript", "jsx": "JavaScript", "mjs": "JavaScript", "cjs": "JavaScript", "ts": "TypeScript", "tsx": "TSX", "mts": "TypeScript", "cts": "TypeScript", "java": "Java",
                   "cpp": "C++", "c": "C", "rs": "Rust", "rb": "Ruby", "php": "PHP", "swift": "Swift",
                   "kt": "Kotlin", "scala": "Scala", "hs": "Haskell", "lua": "Lua", "pl": "Perl",
                   "sh": "Shell", "bash": "Bash", "html": "HTML", "css": "CSS", "json": "JSON",
                   "xml": "XML", "yml": "YAML", "yaml": "YAML", "md": "Markdown", "txt": "Text",
                   "r": "R", "dart": "Dart", "erl": "Erlang", "ex": "Elixir", "exs": "Elixir",
                   "clj": "Clojure", "groovy": "Groovy",
                   "sql": "SQL", "tsv": "TSV", "csv": "CSV", "ini": "INI", "toml": "TOML",
                   "bat": "Batch", "ps1": "PowerShell", "vbs": "VBScript", "f": "Fortran", "f90": "Fortran",
                   "f95": "Fortran", "f03": "Fortran", "f08": "Fortran", "f77": "Fortran", "f2k": "Fortran",
                   "ada": "Ada", "vhdl": "VHDL", "verilog": "Verilog", "asm": "Assembly", "s": "Assembly",
                   "ml": "OCaml", "mli": "OCaml", "nim": "Nim", "d": "D", "zig": "Zig", "rkt": "Racket", "lisp": "Lisp", "scm": "Scheme",
                   "fsharp": "F#", "fs": "F#", "fsx": "F#", "fsproj": "F#", "elm": "Elm", "purescript": "PureScript", "julia": "Julia",
                   }
        return mapping.get(ext, "Unknown")
