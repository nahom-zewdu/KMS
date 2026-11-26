"""Tests for claim-level grounded answer and citation validation."""
from query_engine.evidence import EvidenceCandidate
from query_engine.grounded_answer import GroundedAnswerValidator


def _evidence(**overrides):
    values = dict(
        company_id="company-a",
        evidence_type="code_chunk",
        source="source-code-chunks",
        record_id="chunk-17",
        content="The payment handler calls the billing service.",
        retriever="source-chunk-lexical",
        rank=1,
        repository_id="repo-a",
        snapshot_id="snapshot-a",
        source_revision="revision-a",
        file_path="payments/handler.py",
        content_hash="a" * 64,
        start_line=10,
        end_line=14,
        start_byte=100,
        end_byte=220,
    )
    values.update(overrides)
    return EvidenceCandidate(**values)


def test_valid_claims_derive_sources_from_retrieved_evidence():
    evidence = [_evidence()]
    candidate = evidence[0]
    result = GroundedAnswerValidator().validate(
        {
            "confidence": "high",
            "claims": [
                {"text": "The payment handler calls the billing service.",
                 "evidence_ids": [candidate.evidence_id]}
            ],
        },
        evidence,
    )

    assert result.accepted
    assert result.answer == "The payment handler calls the billing service."
    assert result.sources == ({
        "source": "source-code-chunks",
        "record_id": "chunk-17",
        "evidence_id": candidate.evidence_id,
        "file_path": "payments/handler.py",
    },)
    assert result.to_dict()["claims"] == [{
        "text": "The payment handler calls the billing service.",
        "evidence_ids": [candidate.evidence_id],
    }]


def test_unknown_citation_fails_closed():
    result = GroundedAnswerValidator().validate(
        {"claims": [{"text": "Unsupported claim.", "evidence_ids": ["invented-id"]}]},
        [_evidence()],
    )
    assert not result.accepted
    assert result.abstain_reason == "citation_not_in_retrieved_evidence"
    assert result.sources == ()


def test_every_claim_requires_at_least_one_citation():
    result = GroundedAnswerValidator().validate(
        {"claims": [{"text": "No citation.", "evidence_ids": []}]},
        [_evidence()],
    )
    assert result.abstain_reason == "claim_requires_bounded_citations"


def test_malformed_claims_and_payloads_abstain():
    validator = GroundedAnswerValidator()
    evidence = [_evidence()]
    assert validator.validate("not-json", evidence).abstain_reason == "invalid_grounded_answer"
    assert validator.validate({"claims": "not-a-list"}, evidence).abstain_reason == "no_grounded_claims"
    assert validator.validate({"claims": [None]}, evidence).abstain_reason == "invalid_claim"
    assert validator.validate(
        {"claims": [{"text": " ", "evidence_ids": [evidence[0].evidence_id]}]},
        evidence,
    ).abstain_reason == "invalid_claim_text"


def test_claim_and_answer_bounds_are_enforced():
    candidate = _evidence()
    validator = GroundedAnswerValidator()
    too_many = {"claims": [
        {"text": f"Claim {i}", "evidence_ids": [candidate.evidence_id]}
        for i in range(13)
    ]}
    assert validator.validate(too_many, [candidate]).abstain_reason == "claim_limit_exceeded"

    too_long = {
        "claims": [{
            "text": "x" * 1_201,
            "evidence_ids": [candidate.evidence_id],
        }]
    }
    assert validator.validate(too_long, [candidate]).abstain_reason == "invalid_claim_text"


def test_duplicate_citations_are_deduplicated_and_confidence_is_normalized():
    candidate = _evidence()
    result = GroundedAnswerValidator().validate(
        {
            "confidence": "certain",
            "claims": [{
                "text": "Grounded statement.",
                "evidence_ids": [candidate.evidence_id, candidate.evidence_id],
            }],
        },
        [candidate],
    )
    assert result.accepted
    assert result.confidence == "low"
    assert result.claims[0].evidence_ids == (candidate.evidence_id,)
    assert len(result.sources) == 1


def test_no_claims_means_explicit_abstention():
    result = GroundedAnswerValidator().validate({"claims": []}, [_evidence()])
    assert not result.accepted
    assert result.abstain_reason == "no_grounded_claims"
    assert result.answer == "Not enough validated evidence to answer that yet."
