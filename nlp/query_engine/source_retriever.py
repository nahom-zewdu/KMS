"""Bounded source-code retrieval for Ramp chat explanations.

Only fetches paths already indexed for the authenticated company. The LLM receives
source text as evidence; it does not get to invent file behavior from filenames.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from github import Github, GithubException

logger = logging.getLogger(__name__)

_SUPPORTED_SUFFIXES = (".go", ".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".md")
_MAX_FILES = 4
_MAX_FILE_CHARS = 9000


def _paths_from_text(value: str) -> list[str]:
    return re.findall(
        r"(?:[\w.-]+/)+[\w.-]+\.(?:go|py|ts|tsx|js|jsx|sql|md)",
        value or "",
    )


def _context_file_refs(context: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    active = context.get("active_step")
    steps = [active] if isinstance(active, dict) else (
        context.get("steps") if isinstance(context.get("steps"), list) else []
    )
    for step in steps:
        if not isinstance(step, dict):
            continue
        target = step.get("target") if isinstance(step.get("target"), dict) else {}
        repo = target.get("repo")
        path = target.get("path")
        if isinstance(path, str) and path and not path.startswith(("workflow:", "orient:", "role-surface:")):
            refs.append({"path": path, "repo": repo})
        for item in target.get("files") or []:
            if isinstance(item, dict) and item.get("path"):
                refs.append({
                    "path": str(item["path"]),
                    "repository_id": item.get("repository_id"),
                    "repo": repo,
                })
            elif isinstance(item, str):
                refs.append({"path": item, "repo": repo})
    return refs


def retrieve_source_chunks(
    supabase: Any,
    company_id: str,
    question: str,
    ramp_context: str | None,
    conversation_history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch a few indexed source files that are relevant to a Ramp chat question."""
    q = (question or "").lower()
    explanation_intent = any(term in q for term in (
        "tell me about", "anything about", "what does", "what is in",
        "explain", "describe", "domain layer", "what about domain",
        "these files", "those files", "where should i look",
    ))
    if not explanation_intent:
        return []

    try:
        import json
        context = json.loads(ramp_context) if ramp_context else {}
        if not isinstance(context, dict):
            context = {}
    except (TypeError, json.JSONDecodeError):
        context = {}

    history_paths: list[str] = []
    for message in (conversation_history or [])[-8:]:
        if isinstance(message, dict):
            history_paths.extend(_paths_from_text(str(message.get("content") or "")))
    explicit_paths = _paths_from_text(question)
    refs = _context_file_refs(context)
    if explicit_paths:
        refs = [{"path": path} for path in explicit_paths] + refs
    elif history_paths:
        refs = [{"path": path} for path in history_paths] + refs

    # Resolve repository inventory strictly through this company's repository IDs.
    repository_response = (
        supabase.table("repositories")
        .select("id,full_name,default_branch")
        .eq("company_id", company_id)
        .execute()
    )
    repositories = [
        row for row in (getattr(repository_response, "data", None) or [])
        if isinstance(row, dict) and row.get("id") and row.get("full_name")
    ]
    if not repositories:
        return []
    repo_by_id = {str(row["id"]): row for row in repositories}
    repo_by_name = {str(row["full_name"]): row for row in repositories}
    file_response = (
        supabase.table("codebase_files")
        .select("repository_id,file_path,language,module_path,last_author,last_commit_sha")
        .in_("repository_id", list(repo_by_id))
        .limit(10000)
        .execute()
    )
    indexed_files = [
        row for row in (getattr(file_response, "data", None) or [])
        if isinstance(row, dict) and row.get("file_path")
    ]

    if "domain" in q:
        selected = [
            row for row in indexed_files
            if "domain" in str(row.get("file_path") or "").lower()
            or "domain" in str(row.get("module_path") or "").lower()
        ]
        refs = [{"path": row["file_path"], "repository_id": row.get("repository_id")} for row in selected] + refs
    elif "handler" in q:
        selected = [
            row for row in indexed_files
            if "/handlers/" in str(row.get("file_path") or "")
        ]
        refs = [{"path": row["file_path"], "repository_id": row.get("repository_id")} for row in selected] + refs

    indexed_by_key = {
        (str(row.get("repository_id")), str(row.get("file_path"))): row
        for row in indexed_files
    }
    selected_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        path = str(ref.get("path") or "")
        if not path or not path.endswith(_SUPPORTED_SUFFIXES):
            continue
        preferred_repo_id = str(ref.get("repository_id") or "")
        preferred_repo_name = str(ref.get("repo") or "")
        candidates = []
        if preferred_repo_id:
            candidate = indexed_by_key.get((preferred_repo_id, path))
            if candidate:
                candidates.append(candidate)
        elif preferred_repo_name in repo_by_name:
            repository_id = str(repo_by_name[preferred_repo_name]["id"])
            candidate = indexed_by_key.get((repository_id, path))
            if candidate:
                candidates.append(candidate)
        else:
            candidates.extend(
                row for (repository_id, indexed_path), row in indexed_by_key.items()
                if indexed_path == path
            )
        for row in candidates:
            key = (str(row.get("repository_id")), str(row.get("file_path")))
            if key in seen:
                continue
            seen.add(key)
            selected_rows.append(row)
            if len(selected_rows) >= _MAX_FILES:
                break
        if len(selected_rows) >= _MAX_FILES:
            break

    token = os.getenv("GITHUB_API_TOKEN")
    if not token or not selected_rows:
        return []
    github = Github(token)
    chunks: list[dict[str, Any]] = []
    for row in selected_rows:
        repository = repo_by_id.get(str(row.get("repository_id")))
        if not repository:
            continue
        path = str(row["file_path"])
        try:
            contents = github.get_repo(str(repository["full_name"])).get_contents(
                path, ref=repository.get("default_branch") or None
            )
            if isinstance(contents, list):
                continue
            source_text = contents.decoded_content.decode("utf-8")
        except (GithubException, UnicodeDecodeError, AttributeError) as exc:
            logger.warning(
                "Could not retrieve indexed source file | repo=%s | path=%s | error=%s",
                repository.get("full_name"), path, type(exc).__name__,
            )
            continue
        source_text = source_text[:_MAX_FILE_CHARS]
        if not source_text.strip():
            continue
        chunks.append({
            "content": (
                f"Repository: {repository['full_name']}\n"
                f"File: {path}\n"
                f"Language: {row.get('language') or 'unknown'}\n"
                f"Module: {row.get('module_path') or 'unknown'}\n"
                f"Indexed last author: {row.get('last_author') or 'unknown'}\n"
                f"Source code (truncated if over the retrieval limit):\n{source_text}"
            ),
            "source": "github",
            "record_id": path,
            "file_path": path,
            "company_id": company_id,
            "score": 0.98,
        })
    return chunks
