"""Shared, provenance-preserving candidate contract for hybrid retrieval.

Retrievers produce candidates; fusion ranks them without discarding the source
identity, tenant scope, or source revision needed to validate later citations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from typing import Any, Literal, Mapping


EvidenceType = Literal["code_chunk", "symbol", "occurrence", "event", "graph"]


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    """One bounded retrieval result with stable identity and source provenance.

    Code candidates must identify the exact published snapshot, file, source
    revision, content hash, and source range. Event and graph candidates use
    their tenant-scoped source record identity instead.
    """

    company_id: str
    evidence_type: EvidenceType
    source: str
    record_id: str
    content: str
    retriever: str
    rank: int
    repository_id: str | None = None
    snapshot_id: str | None = None
    source_revision: str | None = None
    file_path: str | None = None
    content_hash: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    start_byte: int | None = None
    end_byte: int | None = None
    raw_score: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject candidates that cannot be safely scoped, ranked, or cited."""
        if not self.company_id or not self.company_id.strip() or self.company_id.strip().lower() == "default":
            raise ValueError("a real company_id is required")
        if self.evidence_type not in {"code_chunk", "symbol", "occurrence", "event", "graph"}:
            raise ValueError("unsupported evidence_type")
        if not self.source or not self.source.strip():
            raise ValueError("source is required")
        if not self.record_id or not self.record_id.strip():
            raise ValueError("record_id is required")
        if not self.retriever or not self.retriever.strip():
            raise ValueError("retriever is required")
        if self.rank < 1:
            raise ValueError("rank must be a positive one-based position")
        if self.raw_score is not None and not math.isfinite(self.raw_score):
            raise ValueError("raw_score must be finite")

        if self.evidence_type in {"code_chunk", "symbol", "occurrence"}:
            required = {
                "repository_id": self.repository_id,
                "snapshot_id": self.snapshot_id,
                "source_revision": self.source_revision,
                "file_path": self.file_path,
                "content_hash": self.content_hash,
                "start_line": self.start_line,
                "end_line": self.end_line,
                "start_byte": self.start_byte,
                "end_byte": self.end_byte,
            }
            missing = [name for name, value in required.items() if value is None or value == ""]
            if missing:
                raise ValueError(f"code evidence is missing provenance fields: {', '.join(missing)}")
            if self.start_line < 1 or self.end_line < self.start_line:
                raise ValueError("code evidence has an invalid line range")
            if self.start_byte < 0 or self.end_byte < self.start_byte:
                raise ValueError("code evidence has an invalid byte range")

    @property
    def evidence_id(self) -> str:
        """Return a deterministic identity scoped to the tenant and source version."""
        if self.evidence_type in {"code_chunk", "symbol", "occurrence"}:
            identity = {
                "company_id": self.company_id,
                "repository_id": self.repository_id,
                "snapshot_id": self.snapshot_id,
                "file_path": self.file_path,
                "start_line": self.start_line,
                "end_line": self.end_line,
                "start_byte": self.start_byte,
                "end_byte": self.end_byte,
                "content_hash": self.content_hash,
                "evidence_type": self.evidence_type,
            }
        else:
            identity = {
                "company_id": self.company_id,
                "source": self.source,
                "record_id": self.record_id,
                "evidence_type": self.evidence_type,
            }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the candidate while preserving its computed stable identity."""
        result = asdict(self)
        result["evidence_id"] = self.evidence_id
        return result
