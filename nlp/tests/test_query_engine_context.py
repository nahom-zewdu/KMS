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

