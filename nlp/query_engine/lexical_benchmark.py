"""Deterministic evaluation harness for the supported lexical retrieval slice.

The fixture's lexical_input is an explicit, curated query signal. This runner
measures retrieval and ranking after those signals are supplied; it does not
measure natural-language query understanding, event retrieval, or hybrid fusion.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

from .evidence import EvidenceCandidate


def run_lexical_benchmark(
    benchmark_path: str | Path,
    retriever: Any,
    *,
    cutoffs: tuple[int, ...] = (1, 5, 10),
) -> dict[str, Any]:
    """Run supported fixture queries and report macro Recall@k and MRR.

    Every returned candidate is checked against the query's company,
    repository, and expected snapshot before it can affect a metric. Queries
    without an explicit lexical_input are reported as unsupported, not scored
    as retrieval misses.
    """
    if not cutoffs or any(cutoff < 1 for cutoff in cutoffs):
        raise ValueError("cutoffs must contain positive integers")

    benchmark = json.loads(Path(benchmark_path).read_text(encoding="utf-8"))
    default_scope = benchmark["default_scope"]
    evaluated: list[dict[str, Any]] = []
    unsupported: list[str] = []

    for query in benchmark["queries"]:
        lexical_input = query.get("lexical_input")
        if lexical_input is None:
            unsupported.append(query["id"])
            continue

        scope = {**default_scope, **query.get("scope", {})}
        candidates: list[EvidenceCandidate] = retriever.retrieve(
            company_id=scope["company_id"],
            repository_id=scope["repository_id"],
            **lexical_input,
        )
        _validate_scope(candidates, scope, query["id"])

        relevant = _expected_evidence(query)
        if not relevant:
            # A lexical query with no declared ground truth cannot produce a
            # meaningful recall denominator.
            unsupported.append(query["id"])
            continue

        ranks = _relevant_ranks(candidates, relevant)
        result: dict[str, Any] = {
            "query_id": query["id"],
            "relevant_count": len(relevant),
            "retrieved_relevant_ranks": ranks,
            "reciprocal_rank": 1.0 / min(ranks) if ranks else 0.0,
        }
        for cutoff in cutoffs:
            result[f"recall_at_{cutoff}"] = (
                sum(rank <= cutoff for rank in ranks) / len(relevant)
            )
        evaluated.append(result)

    metrics: dict[str, float] = {}
    for cutoff in cutoffs:
        key = f"recall_at_{cutoff}"
        metrics[key] = mean(item[key] for item in evaluated) if evaluated else 0.0
    metrics["mrr"] = (
        mean(item["reciprocal_rank"] for item in evaluated) if evaluated else 0.0
    )

    return {
        "benchmark_version": benchmark["version"],
        "evaluated_queries": len(evaluated),
        "unsupported_queries": unsupported,
        "metrics": metrics,
        "query_results": evaluated,
    }


def _expected_evidence(query: Mapping[str, Any]) -> set[str]:
    """Build stable fixture-level relevance keys from declared ground truth."""
    expected = {
        *(f"path:{path}" for path in query.get("expected_paths", [])),
        *(f"symbol:{name}" for name in query.get("expected_symbols", [])),
    }
    return expected


def _relevant_ranks(
    candidates: Iterable[EvidenceCandidate],
    expected: set[str],
) -> list[int]:
    """Return the first rank at which each expected path or symbol appears."""
    first_rank: dict[str, int] = {}
    for candidate in candidates:
        path_key = f"path:{candidate.file_path}" if candidate.file_path else None
        qualified_name = candidate.metadata.get("qualified_name")
        symbol_key = f"symbol:{qualified_name}" if qualified_name else None
        for key in (path_key, symbol_key):
            if key in expected and key not in first_rank:
                first_rank[key] = candidate.rank
    return sorted(first_rank.values())


def _validate_scope(
    candidates: Iterable[EvidenceCandidate],
    scope: Mapping[str, str],
    query_id: str,
) -> None:
    """Fail closed if a retriever returns evidence outside the requested scope."""
    for candidate in candidates:
        if candidate.company_id != scope["company_id"]:
            raise ValueError(f"{query_id}: candidate crossed company scope")
        if candidate.repository_id != scope["repository_id"]:
            raise ValueError(f"{query_id}: candidate crossed repository scope")
        expected_snapshot = scope.get("snapshot_id")
        if expected_snapshot and candidate.snapshot_id != expected_snapshot:
            raise ValueError(f"{query_id}: candidate crossed snapshot scope")
