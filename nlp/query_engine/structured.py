"""Deterministic, tenant-scoped answers for facts already stored in KMS.

The language model is useful for explaining evidence, but it must not invent
counts, repository identity, Ramp state, or ownership. This module handles
those structured facts directly from their authoritative tables.
"""
from __future__ import annotations

import json
import re
from typing import Any


def parse_ramp_context(raw: str | None) -> dict[str, Any]:
    """Parse the versioned Ramp chat context; retain legacy text as opaque context."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"legacy_text": str(raw)}
    return value if isinstance(value, dict) else {"legacy_text": str(raw)}


def _rows(query: Any) -> list[dict[str, Any]]:
    response = query.execute()
    return [row for row in (getattr(response, "data", None) or []) if isinstance(row, dict)]


def _company_inventory(supabase: Any, company_id: str) -> tuple[list[dict], list[dict]]:
    repositories = _rows(
        supabase.table("repositories")
        .select("id,full_name,default_branch,baseline_status,baseline_file_count")
        .eq("company_id", company_id)
        .order("full_name")
    )
    repository_ids = [str(row["id"]) for row in repositories if row.get("id")]
    if not repository_ids:
        return repositories, []
    files = _rows(
        supabase.table("codebase_files")
        .select("id,repository_id,file_path,language,module_path,last_author,last_commit_sha")
        .in_("repository_id", repository_ids)
        .limit(10000)
    )
    return repositories, files


def _context_paths(context: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    history = context.get("conversation_history")
    if isinstance(history, list):
        for message in history[-8:]:
            if isinstance(message, dict):
                paths.extend(re.findall(
                    r"(?:[\w.-]+/)+[\w.-]+\.(?:go|py|ts|tsx|js|jsx|sql|md)",
                    str(message.get("content") or ""),
                ))
    active = context.get("active_step")
    steps = [active] if isinstance(active, dict) else []
    if not steps:
        steps = context.get("steps") if isinstance(context.get("steps"), list) else []
    for step in steps:
        if not isinstance(step, dict):
            continue
        target = step.get("target") if isinstance(step.get("target"), dict) else {}
        path = target.get("path")
        if isinstance(path, str) and path and not path.startswith(("workflow:", "orient:", "role-surface:")):
            paths.append(path)
        for item in target.get("files") or []:
            candidate = item.get("path") if isinstance(item, dict) else item
            if isinstance(candidate, str) and candidate:
                paths.append(candidate)
        for candidate in step.get("paths") or []:
            if isinstance(candidate, str) and candidate:
                paths.append(candidate)
    return list(dict.fromkeys(paths))


def _ownership_answer(
    supabase: Any, company_id: str, context: dict[str, Any], question: str
) -> dict[str, Any] | None:
    entities = _rows(
        supabase.table("entities")
        .select("id,name,type,metadata")
        .eq("company_id", company_id)
        .eq("type", "FILE")
        .limit(10000)
    )
    file_by_id = {str(row["id"]): row for row in entities if row.get("id")}
    wanted_paths = _context_paths(context)
    explicit = re.findall(r"(?:[\w.-]+/)*[\w.-]+\.(?:go|py|ts|tsx|js|jsx|sql|md)", question)
    if explicit:
        wanted_paths = list(dict.fromkeys(explicit + wanted_paths))
    if "handler" in question.lower():
        handler_paths = [path for path in wanted_paths if "/handlers/" in path]
        if handler_paths:
            wanted_paths = handler_paths
    if "domain" in question.lower():
        domain_paths = [path for path in wanted_paths if "domain" in path.lower()]
        if domain_paths:
            wanted_paths = domain_paths
    if wanted_paths:
        wanted = set(wanted_paths)
        file_by_id = {
            key: row for key, row in file_by_id.items()
            if isinstance(row.get("metadata"), dict)
            and row["metadata"].get("file_path") in wanted
        }
    target_ids = list(file_by_id)
    if not target_ids:
        return {
            "answer": "I don't have indexed file records for the files referenced by this Ramp, so I can't identify their owners reliably.",
            "confidence": "low", "sources": [], "owners": [],
            "abstain_reason": "ownership_evidence_unavailable",
        }
    edges = _rows(
        supabase.table("edges")
        .select("source_id,target_id,type,confidence")
        .eq("company_id", company_id)
        .in_("type", ["OWNS", "MAINTAINS"])
        .in_("target_id", target_ids)
        .limit(2000)
    )
    if not edges:
        return {
            "answer": "I couldn't find indexed OWNS or MAINTAINS relationships for the referenced files. I won't infer owners from commit authors or file names.",
            "confidence": "low", "sources": [], "owners": [],
            "abstain_reason": "ownership_evidence_unavailable",
        }
    source_ids = list(dict.fromkeys(str(row["source_id"]) for row in edges if row.get("source_id")))
    people = _rows(
        supabase.table("entities")
        .select("id,name,type")
        .eq("company_id", company_id)
        .in_("id", source_ids)
    )
    names = {str(row["id"]): str(row.get("name") or "") for row in people if row.get("id")}
    grouped: dict[str, list[str]] = {}
    for edge in edges:
        owner = names.get(str(edge.get("source_id") or ""), "")
        target = file_by_id.get(str(edge.get("target_id") or ""))
        metadata = target.get("metadata") if target and isinstance(target.get("metadata"), dict) else {}
        path = str(metadata.get("file_path") or (target or {}).get("name") or "")
        if owner and path:
            grouped.setdefault(owner, []).append(path)
    if not grouped:
        return {
            "answer": "The indexed ownership relationships did not resolve to named people for these files.",
            "confidence": "low", "sources": [], "owners": [],
            "abstain_reason": "ownership_people_unresolved",
        }
    lines = [
        f"{owner}: {', '.join(sorted(set(paths))[:8])}"
        for owner, paths in sorted(grouped.items())
    ]
    answer = "Indexed ownership and maintenance relationships:\n" + "\n".join(lines)
    return {
        "answer": answer,
        "confidence": "high",
        "sources": [{"source": "ownership", "file_path": path} for paths in grouped.values() for path in sorted(set(paths))[:8]][:8],
        "owners": sorted(grouped),
        "abstain_reason": None,
    }


def answer_structured_question(
    supabase: Any, question: str, company_id: str, ramp_context: str | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Return an authoritative answer for supported structured company/Ramp questions."""
    q = re.sub(r"\s+", " ", (question or "").strip().lower())
    context = parse_ramp_context(ramp_context)
    context["conversation_history"] = conversation_history or []

    if re.search(r"\b(owner|owners|who owns|maintainer|maintainers|responsible for)\b", q):
        return _ownership_answer(supabase, company_id, context, question)

    if re.search(r"\b(who|which person)\b.*\b(implemented|authored|wrote|changed|committed)\b|\b(implemented|authored|wrote)\b", q):
        _, files = _company_inventory(supabase, company_id)
        paths = _context_paths(context)
        if "handler" in q:
            handler_paths = [str(row.get("file_path")) for row in files
                             if "api/handlers/" in str(row.get("file_path") or "")]
            paths = handler_paths or paths
        selected = [row for row in files if not paths or row.get("file_path") in set(paths)]
        authors: dict[str, list[str]] = {}
        for row in selected:
            author = str(row.get("last_author") or "").strip()
            path = str(row.get("file_path") or "")
            if author and path:
                authors.setdefault(author, []).append(path)
        if authors:
            detail = "; ".join(
                f"{author}: {', '.join(sorted(set(author_paths))[:8])}"
                for author, author_paths in sorted(authors.items())
            )
            answer = (
                "The indexed last-author metadata records these contributors: "
                + detail
                + ". This identifies the latest recorded author for each file, not everyone who implemented the area."
            )
        else:
            answer = (
                "I don't have reliable author metadata for those files. Ownership relationships are not proof of who implemented them."
            )
        return {
            "answer": answer, "confidence": "medium" if authors else "low",
            "sources": [{"source": "codebase_files", "file_path": path}
                        for paths_for_author in authors.values() for path in paths_for_author][:8],
            "owners": [],
            "abstain_reason": None if authors else "author_metadata_unavailable",
        }

    if re.search(r"\b(those files|these files|tell me about (the )?files|anything about (the )?files|describe (the )?files)\b", q):
        repositories, files = _company_inventory(supabase, company_id)
        history_paths: list[str] = []
        for message in (conversation_history or [])[-8:]:
            if isinstance(message, dict):
                history_paths.extend(re.findall(
                    r"(?:[\w.-]+/)+[\w.-]+\.(?:go|py|ts|tsx|js|jsx|sql|md)",
                    str(message.get("content") or ""),
                ))
        paths = list(dict.fromkeys(history_paths)) or _context_paths(context)
        selected = [row for row in files if row.get("file_path") in set(paths)]
        repo_names = {str(row.get("id")): str(row.get("full_name") or "") for row in repositories}
        if selected:
            lines = []
            for row in selected[:10]:
                parts = [str(row.get("file_path"))]
                if row.get("language"):
                    parts.append(str(row["language"]))
                if row.get("module_path"):
                    parts.append(f"module {row['module_path']}")
                if row.get("last_author"):
                    parts.append(f"last recorded author {row['last_author']}")
                if row.get("repository_id") in repo_names:
                    parts.append(repo_names[row["repository_id"]])
                lines.append(" — ".join(parts))
            return {
                "answer": "Here is what the indexed metadata tells us:\n" + "\n".join(lines)
                    + "\nThis is inventory metadata; it does not by itself explain the files' runtime behavior.",
                "confidence": "high",
                "sources": [{"source": "codebase_files", "file_path": str(row.get("file_path"))}
                            for row in selected[:8]],
                "owners": [], "abstain_reason": None,
            }

    if re.search(r"\b(where are we right now|what am i working on|what are we working on)\b", q):
        active = context.get("active_step") if isinstance(context.get("active_step"), dict) else None
        role = str(context.get("role") or "engineer")
        if active:
            target = active.get("target") if isinstance(active.get("target"), dict) else {}
            repo = target.get("repo")
            paths = _context_paths(context)
            answer = f"You are on step {active.get('order', '?')}: {active.get('title', 'Ramp step')} for the {role} Ramp."
            if repo:
                answer += f" The step targets {repo}."
            if paths:
                answer += " Its referenced files include " + ", ".join(paths[:6]) + "."
        else:
            steps = context.get("steps") if isinstance(context.get("steps"), list) else []
            answer = f"You are viewing the {role} Ramp overview with {len(steps)} steps."
            if steps:
                answer += " The plan is at the overview level; no single active implementation file is selected."
        return {
            "answer": answer, "confidence": "high",
            "sources": [{"source": "ramp_plans", "record_id": str(context.get("plan_id") or "")}],
            "owners": [], "abstain_reason": None,
        }

    if re.search(r"\b(how many|count|number of)\b.*\b(files?|source files?)\b|\b(files?|source files?)\s+(are|is)\s+indexed\b", q):
        repositories, files = _company_inventory(supabase, company_id)
        counts: dict[str, int] = {}
        names = {str(row.get("id")): str(row.get("full_name") or "Unknown repository") for row in repositories}
        for file in files:
            key = names.get(str(file.get("repository_id")), "Unknown repository")
            counts[key] = counts.get(key, 0) + 1
        total = len(files)
        breakdown = "; ".join(f"{name}: {count}" for name, count in sorted(counts.items()))
        answer = f"{total} files are indexed across {len(repositories)} connected repositories."
        if breakdown:
            answer += f" {breakdown}."
        return {
            "answer": answer, "confidence": "high",
            "sources": [{"source": "repositories", "file_path": name} for name in counts],
            "owners": [], "abstain_reason": None,
        }

    if re.search(r"\b(how many|count|number of)\b.*\b(steps?|tasks?)\b|\b(steps?|tasks?)\s+(do we have|are there)\b", q):
        plan_id = str(context.get("plan_id") or "").strip()
        if plan_id:
            rows = _rows(
                supabase.table("ramp_plans")
                .select("id,role,steps")
                .eq("id", plan_id)
                .eq("company_id", company_id)
                .limit(1)
            )
        else:
            role = str(context.get("role") or "").strip().lower().replace(" ", "-")
            query_builder = (
                supabase.table("ramp_plans")
                .select("id,role,steps")
                .eq("company_id", company_id)
                .eq("is_active", True)
            )
            if role:
                query_builder = query_builder.eq("role", role)
            rows = _rows(query_builder.limit(1))
        if rows:
            count = len(rows[0].get("steps") or [])
            return {
                "answer": f"The active {rows[0].get('role', 'company')} Ramp has {count} steps.",
                "confidence": "high",
                "sources": [{"source": "ramp_plans", "record_id": str(rows[0].get("id") or "")}],
                "owners": [], "abstain_reason": None,
            }

    if re.search(r"\b(which|what)\s+(repo|repository)|\bwhat is the repo\b|\bcurrent(ly)?\s+(repo|repository)|\brepo(sitory)?\s+(are we|am i)\s+working on\b|\brepo\s+we're\s+currently\s+working on\b", q):
        repositories, _ = _company_inventory(supabase, company_id)
        active = context.get("active_step") if isinstance(context.get("active_step"), dict) else {}
        target = active.get("target") if isinstance(active.get("target"), dict) else {}
        current_repo = target.get("repo") or context.get("current_repository")
        connected = [str(row.get("full_name")) for row in repositories if row.get("full_name")]
        plan_steps = context.get("steps") if isinstance(context.get("steps"), list) else []
        plan_repositories = sorted({
            str(step.get("target", {}).get("repo"))
            for step in plan_steps
            if isinstance(step, dict)
            and isinstance(step.get("target"), dict)
            and step.get("target", {}).get("repo")
        })
        if current_repo:
            answer = f"The current Ramp step points to {current_repo}."
        elif len(plan_repositories) == 1:
            answer = f"The current Ramp primarily targets {plan_repositories[0]}."
        elif len(plan_repositories) > 1:
            answer = "The current Ramp spans these repositories: " + ", ".join(plan_repositories) + "."
        elif len(connected) == 1:
            answer = f"The connected repository is {connected[0]}."
        elif connected:
            answer = (
                "This Ramp spans multiple connected repositories: "
                + ", ".join(connected)
                + ". The overview does not select one repository as the current working repository."
            )
        else:
            return None
        return {
            "answer": answer, "confidence": "high",
            "sources": [{"source": "repositories", "record_id": ""}],
            "owners": [], "abstain_reason": None,
        }

    if re.search(r"\b(domain|domain layer)\b", q):
        repositories, files = _company_inventory(supabase, company_id)
        matches = [row for row in files if "domain" in str(row.get("file_path") or "").lower() or "domain" in str(row.get("module_path") or "").lower()]
        if matches:
            examples = sorted({str(row.get("file_path")) for row in matches if row.get("file_path")})[:20]
            answer = (
                f"I found {len(matches)} indexed files associated with a domain path/module. "
                "These are structural matches, not proof of what the domain layer is responsible for: "
                + ", ".join(examples)
                + "."
            )
            return {
                "answer": answer, "confidence": "medium",
                "sources": [{"source": "codebase_files", "file_path": path} for path in examples[:8]],
                "owners": [], "abstain_reason": None,
            }
    return None
