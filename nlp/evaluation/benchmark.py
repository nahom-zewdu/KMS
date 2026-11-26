"""Versioned KRT-05 benchmark contracts and fixture loading.

Draft cases are validated but excluded from scored aggregates until a human
reviewer records the review status and identity.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


TaskType = Literal[
    "declaration_discovery",
    "call_site_navigation",
    "passage_retrieval",
    "no_evidence",
    "ambiguous_scope",
    "unsupported",
    "structured_fact",
    "conversation_control",
]
Answerability = Literal["answerable", "partially_answerable", "unanswerable"]
ExpectedIntent = Literal[
    "courtesy", "structured_fact", "declaration_discovery", "call_site_navigation",
    "passage_retrieval", "follow_up", "clarification", "unsupported",
]
ExpectedRoute = Literal[
    "planned_query",
    "abstain",
    "structured_handler",
    "conversation_handler",
    "legacy_unsupported",
]
AbstentionCategory = Literal[
    "no_evidence",
    "ambiguous_repository",
    "ambiguous_symbol",
    "unsupported_intent",
    "insufficient_evidence",
]


class BenchmarkModel(BaseModel):
    """Strict base model: fixture drift must be explicit and reviewed."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BenchmarkScope(BenchmarkModel):
    """Trusted synthetic tenant and source version used for a case."""

    company_id: str = Field(min_length=1, max_length=128)
    repository_id: str | None = Field(default=None, max_length=128)
    snapshot_id: str | None = Field(default=None, max_length=256)
    source_revision: str | None = Field(default=None, max_length=128)


class BenchmarkEvidenceReference(BenchmarkModel):
    """Reference an existing retrieval-fixture case instead of copying labels."""

    retrieval_case_id: str = Field(min_length=1, max_length=64)
    evidence_kind: Literal["declaration", "call_site", "passage"]


class ConversationTurn(BenchmarkModel):
    """Bounded prior conversation context required to test follow-up routing."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1_000)


class BenchmarkCase(BenchmarkModel):
    """One end-to-end case with explicit expected route and review state."""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]+$")
    task_type: TaskType
    expected_intent: ExpectedIntent
    question: str = Field(min_length=1, max_length=1_000)
    scope: BenchmarkScope
    answerability: Answerability
    expected_route: ExpectedRoute
    evidence: tuple[BenchmarkEvidenceReference, ...] = Field(max_length=8)
    conversation_history: tuple[ConversationTurn, ...] = Field(default=(), max_length=8)
    conversation_refs: tuple[str, ...] = Field(default=(), max_length=10)
    required_facts: tuple[str, ...] = Field(max_length=8)
    forbidden_claims: tuple[str, ...] = Field(max_length=8)
    expected_abstention: AbstentionCategory | None = None
    review_status: Literal["draft", "reviewed", "rejected"] = "draft"
    reviewer: str | None = Field(default=None, max_length=128)
    reviewed_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    rationale: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_case_contract(self) -> "BenchmarkCase":
        """Keep answerability, route, abstention, and review metadata consistent."""
        route_intents = {
            "planned_query": {
                "declaration_discovery", "call_site_navigation", "passage_retrieval"
            },
            "structured_handler": {"structured_fact"},
            "conversation_handler": {"follow_up", "clarification", "courtesy"},
            "legacy_unsupported": {"unsupported"},
            "abstain": {
                "declaration_discovery", "call_site_navigation", "passage_retrieval",
                "unsupported",
            },
        }
        if self.expected_intent not in route_intents[self.expected_route]:
            raise ValueError("expected_intent is inconsistent with expected_route")
        task_intents = {
            "declaration_discovery": {"declaration_discovery"},
            "call_site_navigation": {"call_site_navigation"},
            "passage_retrieval": {"passage_retrieval"},
            "no_evidence": {"passage_retrieval"},
            "ambiguous_scope": {"declaration_discovery", "passage_retrieval"},
            "unsupported": {"unsupported"},
            "structured_fact": {"structured_fact"},
            "conversation_control": {"follow_up", "clarification", "courtesy"},
        }
        if self.expected_intent not in task_intents[self.task_type]:
            raise ValueError("expected_intent is inconsistent with task_type")
        if self.expected_route == "planned_query":
            if self.task_type not in {
                "declaration_discovery", "call_site_navigation", "passage_retrieval"
            }:
                raise ValueError("planned_query route requires a supported code task")
            if not self.evidence:
                raise ValueError("planned_query cases require retrieval-fixture evidence")
            if self.answerability == "unanswerable":
                raise ValueError("unanswerable cases cannot expect planned_query")
        if self.expected_route == "abstain":
            if self.answerability != "unanswerable" or self.expected_abstention is None:
                raise ValueError("abstention cases require unanswerable status and a reason")
        elif self.expected_abstention is not None:
            raise ValueError("expected_abstention is only valid for abstain route")
        if self.task_type == "structured_fact" and any((
            self.scope.repository_id,
            self.scope.snapshot_id,
            self.scope.source_revision,
        )):
            raise ValueError(
                "company-level structured facts must not carry repository snapshot scope"
            )
        if self.task_type == "conversation_control":
            if not self.conversation_history or not self.conversation_refs:
                raise ValueError("conversation-control cases require history and references")
        elif self.conversation_history or self.conversation_refs:
            raise ValueError("conversation context is only valid for conversation-control cases")
        if self.task_type == "no_evidence" and self.evidence:
            raise ValueError("no_evidence cases cannot declare positive evidence")
        if self.review_status == "reviewed":
            if not self.reviewer or not self.reviewed_on:
                raise ValueError("reviewed cases require reviewer and reviewed_on")
        elif self.reviewer is not None or self.reviewed_on is not None:
            raise ValueError("unreviewed cases cannot claim reviewer metadata")
        if self.answerability == "answerable" and not self.required_facts and self.expected_route in {
            "planned_query", "structured_handler"
        }:
            raise ValueError("answerable cases require at least one required fact")
        return self


class BenchmarkDataset(BenchmarkModel):
    """Immutable dataset manifest with unique case identities."""

    schema_version: Literal[1]
    dataset_id: str = Field(min_length=1, max_length=100)
    dataset_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(min_length=1, max_length=1_000)
    retrieval_fixture: str = Field(min_length=1, max_length=256)
    default_scope: BenchmarkScope
    cases: tuple[BenchmarkCase, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> "BenchmarkDataset":
        """Reject duplicate case IDs before any evaluation starts."""
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark case IDs must be unique")
        return self

    @property
    def scored_cases(self) -> tuple[BenchmarkCase, ...]:
        """Return only cases explicitly reviewed and approved for scoring."""
        return tuple(case for case in self.cases if case.review_status == "reviewed")


def load_benchmark(path: str | Path) -> BenchmarkDataset:
    """Load and strictly validate a versioned JSON benchmark fixture."""
    return BenchmarkDataset.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def validate_retrieval_references(
    dataset: BenchmarkDataset,
    retrieval_fixture_path: str | Path,
) -> None:
    """Ensure every linked retrieval case exists and matches its declared task."""
    retrieval = json.loads(Path(retrieval_fixture_path).read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in retrieval.get("queries", [])}
    expected_task = {
        "declaration": "declaration_discovery",
        "call_site": "call_site_context",
        "passage": "passage_retrieval",
    }
    for case in dataset.cases:
        for reference in case.evidence:
            source = by_id.get(reference.retrieval_case_id)
            if source is None:
                raise ValueError(
                    f"{case.id}: unknown retrieval case {reference.retrieval_case_id}"
                )
            if source.get("task_type") != expected_task[reference.evidence_kind]:
                raise ValueError(
                    f"{case.id}: retrieval case {reference.retrieval_case_id} "
                    "has the wrong task type"
                )
            if not (
                source.get("expected_symbols")
                or source.get("expected_ranges")
                or source.get("expected_paths")
            ):
                raise ValueError(
                    f"{case.id}: linked retrieval case has no expected evidence"
                )
