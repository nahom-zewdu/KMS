"""Tests for conservative deterministic query classification."""
import pytest

from query_engine.query_plan import PlanDisposition, QueryIntent, QueryScope
from query_engine.query_planner import classify_query


SCOPE = QueryScope(company_id="company-1", repository_id="repo-1")


@pytest.mark.parametrize("query", ["Thanks!", "hello", "Good morning"])
def test_courtesy_does_not_trigger_retrieval(query):
    plan = classify_query(query, scope=SCOPE)
    assert plan.intent is QueryIntent.COURTESY
    assert plan.disposition is PlanDisposition.READY


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("Where is calculate_tax called?", QueryIntent.CALL_SITE_NAVIGATION),
        ("Who calls Invoice.total?", QueryIntent.CALL_SITE_NAVIGATION),
        ("Find the definition of calculate_tax", QueryIntent.DECLARATION_DISCOVERY),
        ("Where is Invoice.total defined?", QueryIntent.DECLARATION_DISCOVERY),
        ("How many files are in this repository?", QueryIntent.STRUCTURED_FACT),
        ("Who owns the billing service?", QueryIntent.STRUCTURED_FACT),
        ("Explain the billing handler implementation", QueryIntent.PASSAGE_RETRIEVAL),
        ("How does the API handler work?", QueryIntent.PASSAGE_RETRIEVAL),
        ("Show me code in billing/invoice.py", QueryIntent.PASSAGE_RETRIEVAL),
    ],
)
def test_supported_query_shapes_are_classified_conservatively(query, intent):
    assert classify_query(query, scope=SCOPE).intent is intent


def test_query_plan_preserves_trusted_scope():
    plan = classify_query("Explain the API handler", scope=SCOPE)
    assert plan.scope is SCOPE


def test_classifier_rejects_missing_or_untrusted_scope():
    with pytest.raises(ValueError, match="trusted QueryScope"):
        classify_query("Explain the API handler", scope="company-1")
    with pytest.raises(ValueError, match="non-empty"):
        classify_query("   ", scope=SCOPE)


def test_ambiguous_follow_up_does_not_fall_through_to_retrieval():
    plan = classify_query("What?", scope=SCOPE)
    assert plan.intent is QueryIntent.CLARIFICATION
    assert plan.disposition is PlanDisposition.NEEDS_CLARIFICATION
    assert plan.ambiguity_reason


def test_acknowledgement_requires_explicit_conversation_context_and_refs():
    history = [{"role": "assistant", "content": "I found the invoice handler."}]
    unresolved = classify_query("yes", scope=SCOPE, conversation_history=history)
    assert unresolved.intent is QueryIntent.CLARIFICATION
    resolved = classify_query(
        "yes", scope=SCOPE, conversation_history=history,
        conversation_refs=("evidence-1",),
    )
    assert resolved.intent is QueryIntent.FOLLOW_UP
    assert resolved.conversation_refs == ("evidence-1",)


def test_follow_up_does_not_invent_conversation_references():
    plan = classify_query(
        "Can you explain that?", scope=SCOPE,
        conversation_history=[{"role": "assistant", "content": "Previous answer"}],
    )
    assert plan.intent is QueryIntent.CLARIFICATION
    assert plan.conversation_refs == ()


def test_explicit_identifier_and_path_extraction():
    tick = chr(96)
    plan = classify_query(
        "Explain " + tick + "Invoice.total" + tick + " in billing/invoice.py",
        scope=SCOPE,
    )
    assert "billing/invoice.py" in plan.file_paths
    assert "Invoice.total" in plan.qualified_names
    assert "Invoice.total" in plan.identifiers



def test_source_file_path_is_not_misclassified_as_a_symbol_candidate():
    plan = classify_query(
        "Find the declaration of process_task in worker_a.py.",
        scope=SCOPE,
    )

    assert plan.file_paths == ("worker_a.py",)
    assert plan.identifiers == ("process_task",)
    assert plan.qualified_names == ()



def test_structured_count_with_explicit_company_reference_is_not_follow_up():
    plan = classify_query(
        "How many repositories are connected to this company?",
        scope=SCOPE,
    )

    assert plan.intent is QueryIntent.STRUCTURED_FACT


def test_extraction_is_bounded_and_deduplicated():
    tick = chr(96)
    query = "Explain " + " ".join(tick + f"symbol_{i}" + tick for i in range(35))
    plan = classify_query(query, scope=SCOPE)
    assert len(plan.identifiers) <= 50
    assert len(plan.terms) <= 20
    assert len(plan.file_paths) <= 50


def test_unknown_non_engineering_request_abstains():
    plan = classify_query("What is the weather tomorrow?", scope=SCOPE)
    assert plan.intent is QueryIntent.UNSUPPORTED
    assert plan.disposition is PlanDisposition.ABSTAIN
    assert plan.abstention_reason == "unsupported_query"


def test_symbol_resolution_is_never_guessed_by_classifier():
    plan = classify_query("Where is calculate_tax called?", scope=SCOPE)
    assert plan.intent is QueryIntent.CALL_SITE_NAVIGATION
    assert plan.resolved_symbol is None


def test_conversation_reference_input_must_be_a_sequence_of_strings():
    with pytest.raises(ValueError, match="sequence of strings"):
        classify_query("yes", scope=SCOPE, conversation_refs="not-a-reference-list")
    with pytest.raises(ValueError, match="only strings"):
        classify_query("yes", scope=SCOPE, conversation_refs=("valid", 42))

@pytest.mark.parametrize(
    "query",
    [
        "Where is product availability checked?",
        "Where is the product reservation operation defined?",
        "Where is SKU normalization implemented?",
        "Where is the invoice subtotal calculated?",
        "Where is invoice tax calculated?",
    ],
)
def test_krt05_declaration_query_shapes_have_expected_intent(query):
    assert classify_query(query, scope=SCOPE).intent is QueryIntent.DECLARATION_DISCOVERY

@pytest.mark.parametrize(
    "query",
    [
        "What happens when a product is unavailable for reservation?",
        "How is an SKU normalized?",
        "How is the invoice subtotal computed?",
        "How is tax rounded for an invoice?",
        "What condition makes a payment authorization invalid?",
        "Where is the Kubernetes deployment reconciler implemented?",
        "Where is the invoice chargeback dispute workflow implemented?",
        "Where is the password reset email token expiry policy implemented?",
    ],
)
def test_krt05_passage_query_shapes_have_expected_intent(query):
    assert classify_query(query, scope=SCOPE).intent is QueryIntent.PASSAGE_RETRIEVAL

@pytest.mark.parametrize(
    "query",
    [
        "Who owns the billing module and approves changes to it?",
        "What happens at runtime when the payment provider is unavailable?",
    ],
)
def test_krt05_unsupported_query_shapes_abstain(query):
    plan = classify_query(query, scope=SCOPE)
    assert plan.intent is QueryIntent.UNSUPPORTED
    assert plan.disposition is PlanDisposition.ABSTAIN

@pytest.mark.parametrize(
    "query",
    [
        "Which code checks availability before reserving a product?",
        "Where does catalog search normalize an SKU before checking availability?",
        "Where are alternative product recommendations normalized?",
        "Where does invoice construction call the subtotal calculator?",
        "Where does invoice construction calculate tax from the subtotal?",
    ],
)
def test_krt05_call_site_query_shapes_have_expected_intent(query):
    assert classify_query(query, scope=SCOPE).intent is QueryIntent.CALL_SITE_NAVIGATION

@pytest.mark.parametrize(
    "query",
    [
        "Where is SKU normalization implemented?",
        "Where is the HTTP API handler defined?",
        "Where is OAuth token validation implemented?",
    ],
)
def test_uppercase_acronyms_are_not_inferred_as_symbol_identifiers(query):
    plan = classify_query(query, scope=SCOPE)

    assert plan.identifiers == ()


@pytest.mark.parametrize(
    ("query", "identifier"),
    [
        ("Where is normalize_sku implemented?", "normalize_sku"),
        ("Where is findAvailable defined?", "findAvailable"),
        ("Where is HTTPParser implemented?", "HTTPParser"),
    ],
)
def test_explicit_symbol_shaped_names_remain_identifiers(query, identifier):
    plan = classify_query(query, scope=SCOPE)

    assert identifier in plan.identifiers

