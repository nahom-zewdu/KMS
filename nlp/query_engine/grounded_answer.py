"""Validation for claim-level citations in grounded KMS answers.

This module validates citation identity and derives public source references from
retrieved evidence. It does not claim to prove semantic entailment between a
claim and its cited source; that requires separate evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

from .evidence import EvidenceCandidate


MAX_GROUNDED_CLAIMS = 12
MAX_CLAIM_LENGTH = 1_200
MAX_CITATIONS_PER_CLAIM = 5
MAX_GROUNDED_ANSWER_LENGTH = 6_000


@dataclass(frozen=True, slots=True)
class GroundedClaim:
    """One factual statement with references to retrieved evidence identities."""

    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroundedAnswerResult:
    """Validated answer contract with citations derived only from evidence."""

    answer: str
    confidence: str
    claims: tuple[GroundedClaim, ...]
    sources: tuple[dict[str, str], ...]
    abstain_reason: str | None = None

    @property
    def accepted(self) -> bool:
        """Whether the answer contains at least one validated claim."""
        return bool(self.claims) and self.abstain_reason is None

    def to_dict(self) -> dict[str, Any]:
        """Return the stable public answer shape plus claim-level citations."""
        return {
            "answer": self.answer,
            "confidence": self.confidence,
            "sources": [dict(source) for source in self.sources],
            "owners": [],
            "abstain_reason": self.abstain_reason,
            "claims": [
                {"text": claim.text, "evidence_ids": list(claim.evidence_ids)}
                for claim in self.claims
            ],
        }


class GroundedAnswerValidator:
    """Fail closed on malformed claims or citations outside retrieved evidence."""

    def validate(
        self,
        payload: Mapping[str, Any] | Any,
        evidence: Sequence[EvidenceCandidate],
    ) -> GroundedAnswerResult:
        """Validate bounded claim text and require known evidence IDs per claim."""
        if isinstance(payload, str):
            text = payload.strip()
            if text.startswith("```"):
                text = text.strip("`").strip()
                if text[:4].lower() == "json":
                    text = text[4:].strip()
            try:
                payload = json.loads(text)
            except (TypeError, ValueError):
                return self._abstain("invalid_grounded_answer")
        if not isinstance(payload, Mapping):
            return self._abstain("invalid_grounded_answer")

        evidence_by_id = {
            item.evidence_id: item
            for item in evidence
            if isinstance(item, EvidenceCandidate)
        }
        raw_claims = payload.get("claims")
        if not isinstance(raw_claims, list) or not raw_claims:
            return self._abstain("no_grounded_claims")
        if len(raw_claims) > MAX_GROUNDED_CLAIMS:
            return self._abstain("claim_limit_exceeded")

        claims: list[GroundedClaim] = []
        used_ids: list[str] = []
        seen_ids: set[str] = set()
        total_length = 0

        for raw in raw_claims:
            if not isinstance(raw, Mapping):
                return self._abstain("invalid_claim")
            text = raw.get("text")
            ids = raw.get("evidence_ids")
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_CLAIM_LENGTH:
                return self._abstain("invalid_claim_text")
            if not isinstance(ids, list) or not ids or len(ids) > MAX_CITATIONS_PER_CLAIM:
                return self._abstain("claim_requires_bounded_citations")
            if any(not isinstance(value, str) or not value for value in ids):
                return self._abstain("invalid_citation_id")

            unique_ids = tuple(dict.fromkeys(ids))
            unknown = [value for value in unique_ids if value not in evidence_by_id]
            if unknown:
                return self._abstain("citation_not_in_retrieved_evidence")

            total_length += len(text.strip())
            if total_length > MAX_GROUNDED_ANSWER_LENGTH:
                return self._abstain("answer_length_exceeded")

            claim = GroundedClaim(text=text.strip(), evidence_ids=unique_ids)
            claims.append(claim)
            for evidence_id in unique_ids:
                if evidence_id not in seen_ids:
                    seen_ids.add(evidence_id)
                    used_ids.append(evidence_id)

        confidence = str(payload.get("confidence") or "low").lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"

        sources: list[dict[str, str]] = []
        for evidence_id in used_ids:
            item = evidence_by_id[evidence_id]
            source = {
                "source": item.source,
                "record_id": item.record_id,
                "evidence_id": evidence_id,
            }
            if item.file_path:
                source["file_path"] = item.file_path
            sources.append(source)

        return GroundedAnswerResult(
            answer=" ".join(claim.text for claim in claims),
            confidence=confidence,
            claims=tuple(claims),
            sources=tuple(sources),
        )

    @staticmethod
    def _abstain(reason: str) -> GroundedAnswerResult:
        return GroundedAnswerResult(
            answer="Not enough validated evidence to answer that yet.",
            confidence="low",
            claims=(),
            sources=(),
            abstain_reason=reason,
        )
