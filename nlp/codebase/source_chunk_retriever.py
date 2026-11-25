"""Tenant- and active-snapshot-scoped lexical retrieval over source chunks."""
from __future__ import annotations

from typing import Any

from query_engine.evidence import EvidenceCandidate


class SourceChunkRetriever:
    """Retrieve source passages using bounded literal term matches."""

    def __init__(self, supabase: Any, *, max_results: int = 50) -> None:
        if max_results < 1 or max_results > 500:
            raise ValueError("max_results must be between 1 and 500")
        self.supabase = supabase
        self.max_results = max_results

    def retrieve(
        self,
        *,
        company_id: str,
        repository_id: str,
        terms: list[str],
    ) -> list[EvidenceCandidate]:
        """Return deduplicated chunks matching any literal term in active snapshot."""
        if not company_id or not company_id.strip() or company_id.strip().lower() == "default":
            raise ValueError("a real company_id is required")
        if not repository_id or not repository_id.strip():
            raise ValueError("repository_id is required")
        normalized = list(dict.fromkeys(term.strip()[:200] for term in terms if term and term.strip()))
        if not normalized:
            return []

        repo = (
            self.supabase.table("repositories")
            .select("id,company_id,active_snapshot_id")
            .eq("id", repository_id)
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
        if not repo.data:
            return []
        snapshot_id = repo.data[0].get("active_snapshot_id")
        if not snapshot_id:
            return []

        rows_by_id: dict[str, dict[str, Any]] = {}
        for term in normalized[:20]:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            response = (
                self.supabase.table("source_code_chunks")
                .select("*")
                .eq("company_id", company_id)
                .eq("repository_id", repository_id)
                .eq("snapshot_id", snapshot_id)
                .ilike("content", f"%{escaped}%")
                .order("file_path")
                .order("start_byte")
                .limit(self.max_results)
                .execute()
            )
            for row in response.data or []:
                rows_by_id.setdefault(str(row["chunk_id"]), row)

        def relevance(row: dict[str, Any]) -> tuple[int, int, str, int]:
            content = str(row.get("content") or "").casefold()
            matched = [term.casefold() for term in normalized if term.casefold() in content]
            frequency = sum(content.count(term) for term in matched)
            return (
                -len(matched),
                -frequency,
                str(row.get("file_path") or ""),
                int(row.get("start_byte") or 0),
            )

        ordered = sorted(rows_by_id.values(), key=relevance)[: self.max_results]
        candidates: list[EvidenceCandidate] = []
        for row in ordered:
            content = str(row["content"])
            matched_terms = [
                term for term in normalized if term.casefold() in content.casefold()
            ]
            candidates.append(EvidenceCandidate(
                company_id=company_id,
                evidence_type="code_chunk",
                source="source-code-chunks",
                record_id=str(row["chunk_id"]),
                content=content,
                retriever="source-chunk-lexical",
                rank=len(candidates) + 1,
                repository_id=repository_id,
                snapshot_id=str(snapshot_id),
                source_revision=str(row["source_revision"]),
                file_path=str(row["file_path"]),
                content_hash=str(row["content_hash"]),
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
                start_byte=int(row["start_byte"]),
                end_byte=int(row["end_byte"]),
                raw_score=float(len(matched_terms)),
                metadata={
                    "chunk_index": row.get("chunk_index"),
                    "chunker_version": row.get("chunker_version"),
                    "source_content_hash": row.get("source_content_hash"),
                    "match_terms": matched_terms,
                },
            ))
        return candidates
