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

