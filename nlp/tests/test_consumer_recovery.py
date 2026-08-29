import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from redis.exceptions import ConnectionError

sys.path.insert(0, str(Path(__file__).parents[1]))

from worker.consumer import RedisStreamConsumer


class FakeRedis:
    def __init__(self, pending=None, reclaim_error=None):
        self.pending = pending or []
        self.reclaim_error = reclaim_error
        self.claimed = []
        self.acked = []
        self.xautoclaim_calls = []

    def xgroup_create(self, *args, **kwargs):
        return True

    def xautoclaim(self, stream, group, consumer, min_idle_time, start_id, count):
        self.xautoclaim_calls.append((stream, group, consumer, min_idle_time, start_id, count))
        if self.reclaim_error:
            raise self.reclaim_error

        entries = []
        for message_id, data, idle_ms in self.pending:
            if idle_ms >= min_idle_time and message_id not in self.claimed:
                self.claimed.append(message_id)
                entries.append((message_id, data))
        return "0-0", entries

    def xack(self, stream, group, message_id):
        self.acked.append((stream, group, message_id))

    def xdel(self, stream, message_id):
        return 1


class RecordingHandler:
    def __init__(self, error=None):
        self.jobs = []
        self.error = error

    def process(self, job, stream, message_id, redis_client):
        self.jobs.append((job, stream, message_id))
        if self.error:
            raise self.error


class ConsumerRecoveryTests(unittest.TestCase):
    def make_consumer(self, redis, handler, idle_timeout=1000):
        with patch("worker.consumer.init_redis", return_value=redis):
            consumer = RedisStreamConsumer(
                ["slack_jobs"],
                "ingestion",
                {"slack_jobs": handler},
                pending_idle_timeout_ms=idle_timeout,
            )
        consumer.running = True
        return consumer

    @staticmethod
    def message():
        return {
            "record_id": "r1",
            "source": "slack",
            "content": "hello",
            "event_type": "message",
            "company_id": "company-1",
        }

    def test_idle_message_is_reclaimed_and_uses_normal_handler_path(self):
        handler = RecordingHandler()
        redis = FakeRedis(
            pending=[("1-0", {"data": json.dumps(self.message())}, 1000)]
        )
        consumer = self.make_consumer(redis, handler, idle_timeout=1000)

        consumer._recover_pending()

        self.assertEqual(len(handler.jobs), 1)
        self.assertEqual(handler.jobs[0][2], "1-0")
        self.assertEqual(redis.acked, [("slack_jobs", "ingestion", "1-0")])
        self.assertEqual(redis.xautoclaim_calls[0][3], 1000)

    def test_message_below_idle_threshold_is_not_reclaimed(self):
        handler = RecordingHandler()
        redis = FakeRedis(
            pending=[("1-0", {"data": json.dumps(self.message())}, 999)]
        )
        consumer = self.make_consumer(redis, handler, idle_timeout=1000)

        consumer._recover_pending()

        self.assertEqual(handler.jobs, [])
        self.assertEqual(redis.acked, [])
        self.assertEqual(redis.claimed, [])

    def test_processing_failure_leaves_reclaimed_message_pending(self):
        handler = RecordingHandler(error=RuntimeError("processing failed"))
        redis = FakeRedis(
            pending=[("1-0", {"data": json.dumps(self.message())}, 1000)]
        )
        consumer = self.make_consumer(redis, handler)

        consumer._recover_pending()

        self.assertEqual(redis.acked, [])
        self.assertEqual(redis.claimed, ["1-0"])

    def test_active_message_below_threshold_is_not_stolen_by_another_consumer(self):
        handler = RecordingHandler()
        redis = FakeRedis(
            pending=[("1-0", {"data": json.dumps(self.message())}, 100)]
        )
        first = self.make_consumer(redis, handler, idle_timeout=1000)
        second = self.make_consumer(redis, handler, idle_timeout=1000)

        first._recover_pending()
        second._recover_pending()

        self.assertEqual(handler.jobs, [])
        self.assertEqual(redis.claimed, [])
        self.assertNotEqual(first.consumer_name, second.consumer_name)

    def test_reclaim_error_is_visible(self):
        handler = RecordingHandler()
        redis = FakeRedis(reclaim_error=ConnectionError("redis unavailable"))
        consumer = self.make_consumer(redis, handler)

        with self.assertRaisesRegex(RuntimeError, "pending-message recovery failed"):
            consumer._recover_pending()


if __name__ == "__main__":
    unittest.main()
