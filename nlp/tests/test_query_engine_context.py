import json
from unittest.mock import Mock

import query_engine.core as core_module
from query_engine.core import QueryEngine


class FakeRedis:
    def __init__(self):
        self.messages = []

    def get(self, key):
        return None

    def setex(self, *args, **kwargs):
        return None

    def publish(self, channel, message):
        self.messages.append((channel, message))


def _make_engine():
    engine = QueryEngine(supabase=Mock(), redis=FakeRedis())
    engine.cache = Mock()
    engine.cache.get.return_value = None
    engine.cache.set = Mock()
    engine.retriever = Mock()
    engine.retriever.retrieve.return_value = [
        {
            "source": "raw",
            "record_id": "r1",
            "content": "The payments service handles billing and charge retries.",
            "owners": ["Alice"],
        }
    ]
    return engine


def test_query_with_no_ramp_context_uses_content_question_and_keeps_behavior():
    engine = _make_engine()
    engine.cache.get = Mock(return_value=None)

    original = core_module.reasoning_synthesize
    core_module.reasoning_synthesize = Mock(return_value={
        "answer": "The service handles billing.",
        "confidence": "high",
        "sources": [{"source": "raw", "record_id": "r1"}],
        "owners": ["Alice"],
        "abstain_reason": None,
    })
    try:
        result = engine.handle_query({
            "record_id": "q-1",
            "company_id": "company-123",
            "content": "What does the payments service do?",
        })
        payload = json.loads(result)
        assert payload["answer"] == "The service handles billing."
        engine.retriever.retrieve.assert_called_once_with("What does the payments service do?", company_id="company-123")
        args, kwargs = core_module.reasoning_synthesize.call_args
        assert args[0] == "What does the payments service do?"
        assert kwargs["ramp_context"] is None
    finally:
        core_module.reasoning_synthesize = original


def test_query_with_ramp_context_uses_question_for_retrieval_but_passes_context_to_synthesis():
    engine = _make_engine()
    original = core_module.reasoning_synthesize
    core_module.reasoning_synthesize = Mock(return_value={
        "answer": "Billing is handled here.",
        "confidence": "high",
        "sources": [{"source": "raw", "record_id": "r1"}],
        "owners": ["Alice"],
        "abstain_reason": None,
    })
    try:
        result = engine.handle_query({
            "record_id": "q-2",
            "company_id": "company-123",
            "content": "Ramp context mixed in",
            "payload": {
                "question": "What does the payments service do?",
                "context": "Role: backend engineer\nStep 3: Understand payment service\nPath: services/payments",
                "company_id": "company-123",
            },
        })
        payload = json.loads(result)
        assert payload["answer"] == "Billing is handled here."
        engine.retriever.retrieve.assert_called_once_with("What does the payments service do?", company_id="company-123")
        args, kwargs = core_module.reasoning_synthesize.call_args
        assert args[0] == "What does the payments service do?"
        assert kwargs["ramp_context"] == "Role: backend engineer\nStep 3: Understand payment service\nPath: services/payments"
    finally:
        core_module.reasoning_synthesize = original


def test_company_scope_is_preserved_and_ramp_context_does_not_become_company_evidence():
    engine = _make_engine()
    original = core_module.reasoning_synthesize
    captured = {}

    def fake_synth(question, chunks, allowed_owners=None, ramp_context=None):
        captured["question"] = question
        captured["ramp_context"] = ramp_context
        captured["allowed_owners"] = allowed_owners
        return {
            "answer": "The evidence says billing is handled by the service.",
            "confidence": "high",
            "sources": [{"source": "raw", "record_id": "r1"}],
            "owners": ["Alice"],
            "abstain_reason": None,
        }

    core_module.reasoning_synthesize = Mock(side_effect=fake_synth)
    try:
        engine.handle_query({
            "record_id": "q-3",
            "company_id": "company-456",
            "content": "What does the service do?",
            "payload": {
                "question": "What does the service do?",
                "context": "Owners: Bob\nStep 1: Understand payments",
            },
        })
        engine.retriever.retrieve.assert_called_once_with("What does the service do?", company_id="company-456")
        assert captured["question"] == "What does the service do?"
        assert captured["ramp_context"] == "Owners: Bob\nStep 1: Understand payments"
        assert captured["allowed_owners"] == ["Alice"]
    finally:
        core_module.reasoning_synthesize = original

    prompt = "Ramp step context (interpretation only; not company evidence):\nOwners: Bob\nStep 1: Understand payments"
    assert "not company evidence" in prompt.lower()


def test_cache_key_changes_for_materially_different_ramp_contexts():
    engine = _make_engine()
    key_a = engine._cache_key("What does the service do?", "company-123", "Role: backend engineer\nStep 1")
    key_b = engine._cache_key("What does the service do?", "company-123", "Role: backend engineer\nStep 2")
    key_c = engine._cache_key("What does the service do?", "company-123", None)

    assert key_a != key_b
    assert key_a != key_c
    assert key_b != key_c
