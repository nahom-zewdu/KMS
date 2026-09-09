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

