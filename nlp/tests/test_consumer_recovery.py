import json
import sys
import threading
import time
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
        self.deleted = []
        self.groups = []
        self.leases = {}
        self.dead_letters = []
        self.xclaim_calls = []

    def xgroup_create(self, stream, group, id, mkstream):
        self.groups.append((stream, group, id, mkstream))

    def set(self, key, value, nx=False, px=None):
        if nx and key in self.leases:
            return None
        self.leases[key] = value
        return True

    def eval(self, script, numkeys, *args):
        if "PEXPIRE" in script:
            key, token = args[:2]
            return 1 if self.leases.get(key) == token else 0
        if "XADD" in script:
            dedupe_key, stream = args[:2]
            if dedupe_key in self.leases:
                return self.leases[dedupe_key]
            fields = args[3:]
            entry = dict(zip(fields[::2], fields[1::2]))
            self.dead_letters.append((stream, entry))
            self.leases[dedupe_key] = "2-0"
            return "2-0"
        key, token = args[:2]
        if self.leases.get(key) == token:
            del self.leases[key]
            return 1
        return 0

    def xpending_range(self, stream, group, min_id, max_id, count):
        if self.reclaim_error:
            raise self.reclaim_error
        exact = min_id == max_id
        cursor = min_id[1:] if min_id.startswith("(") else min_id
        rows = []
        for item in self.pending:
            message_id = item["message_id"]
            if exact and message_id != min_id:
                continue
            if not exact and cursor != "-" and message_id <= cursor:
                continue
            rows.append(item)
        return rows[:count]

    def xclaim(self, stream, group, consumer, min_idle_time, message_ids):
        self.xclaim_calls.append((stream, group, consumer, min_idle_time, message_ids))
        claimed = []
        for message_id in message_ids:
            item = next((p for p in self.pending if p["message_id"] == message_id), None)
            if item is not None:
                self.claimed.append(message_id)
                item["consumer"] = consumer
                item["times_delivered"] += 1
                claimed.append((message_id, item["data"]))
        return claimed

    def xack(self, stream, group, message_id):
        self.acked.append((stream, group, message_id))
        self.pending = [p for p in self.pending if p["message_id"] != message_id]
        return 1

    def xdel(self, stream, message_id):
        self.deleted.append((stream, message_id))
        return 1


class RecordingHandler:
    def __init__(self, error=None):
        self.jobs = []
        self.error = error

    def process(self, job, stream, message_id, redis_client):
        self.jobs.append((job, stream, message_id))
        if self.error:
            raise self.error


class IdempotentSideEffectHandler:
    def __init__(self):
        self.effects = set()
        self.calls = 0

    def process(self, job, stream, message_id, redis_client):
        self.calls += 1
        self.effects.add((job["company_id"], job["record_id"]))
        if self.calls == 1:
            raise RuntimeError("crashed after side effect")


class ConsumerRecoveryTests(unittest.TestCase):
    def make_consumer(self, redis, handler, idle_timeout=1000, max_deliveries=5):
        with patch("worker.consumer.init_redis", return_value=redis):
            consumer = RedisStreamConsumer(
                ["slack_jobs"],
                "ingestion",
                {"slack_jobs": handler},
                pending_idle_timeout_ms=idle_timeout,
                lease_ttl_ms=3000,
                max_deliveries=max_deliveries,
            )
        consumer.running = True
        return consumer

    @staticmethod
    def message(company_id="company-1"):
        return {
            "record_id": "r1",
            "source": "slack",
            "content": "hello",
            "event_type": "message",
            "company_id": company_id,
        }

    @staticmethod
    def pending(message_id="1-0", idle_ms=1000, deliveries=1, company_id="company-1"):
        return {
            "message_id": message_id,
            "time_since_delivered": idle_ms,
            "times_delivered": deliveries,
            "consumer": "previous-worker",
            "data": {"data": json.dumps(ConsumerRecoveryTests.message(company_id))},
        }

    def test_new_consumer_group_starts_at_existing_stream_entries(self):
        redis = FakeRedis()
        self.make_consumer(redis, RecordingHandler())
        self.assertEqual(redis.groups, [("slack_jobs", "ingestion", "0-0", True)])

    def test_idle_message_is_claimed_after_expired_lease_and_processed(self):
        handler = RecordingHandler()
        redis = FakeRedis(pending=[self.pending()])
        consumer = self.make_consumer(redis, handler)

        consumer._recover_pending()

        self.assertEqual(len(handler.jobs), 1)
        self.assertEqual(handler.jobs[0][2], "1-0")
        self.assertEqual(redis.acked, [("slack_jobs", "ingestion", "1-0")])
        self.assertEqual(redis.deleted, [])
        self.assertEqual(redis.xclaim_calls[0][3], 0)

    def test_active_worker_lease_prevents_reclamation_even_when_job_is_old(self):
        handler = RecordingHandler()
        redis = FakeRedis(pending=[self.pending(idle_ms=120000)])
        consumer = self.make_consumer(redis, handler)
        key = consumer._lease_key("slack_jobs", "1-0")
        redis.leases[key] = "live-worker-token"

        consumer._recover_pending()

        self.assertEqual(handler.jobs, [])
        self.assertEqual(redis.claimed, [])

    def test_pending_entry_below_idle_threshold_is_not_reclaimed(self):
        handler = RecordingHandler()
        redis = FakeRedis(pending=[self.pending(idle_ms=999)])
        consumer = self.make_consumer(redis, handler, idle_timeout=1000)

        consumer._recover_pending()

        self.assertEqual(handler.jobs, [])
        self.assertEqual(redis.claimed, [])

    def test_retry_backoff_grows_with_delivery_count(self):
        handler = RecordingHandler()
        redis = FakeRedis(pending=[self.pending(idle_ms=7000, deliveries=4)])
        consumer = self.make_consumer(redis, handler, idle_timeout=1000)

        consumer._recover_pending()

        self.assertEqual(handler.jobs, [])
        self.assertEqual(redis.claimed, [])

    def test_failed_handler_remains_pending_until_delivery_budget_exhausted(self):
        handler = RecordingHandler(error=RuntimeError("processing failed"))
        redis = FakeRedis(pending=[self.pending(deliveries=1)])
        consumer = self.make_consumer(redis, handler, max_deliveries=3)

        consumer._process_message("slack_jobs", "1-0", self.pending()["data"], handler)

        self.assertEqual(redis.acked, [])
        self.assertEqual(redis.dead_letters, [])

    def test_exhausted_job_is_routed_to_dead_letter_before_ack(self):
        handler = RecordingHandler(error=RuntimeError("terminal failure"))
        redis = FakeRedis(pending=[self.pending(deliveries=5)])
        consumer = self.make_consumer(redis, handler, max_deliveries=5)

        consumer._process_message("slack_jobs", "1-0", self.pending()["data"], handler)

        self.assertEqual(len(redis.dead_letters), 1)
        stream, entry = redis.dead_letters[0]
        self.assertEqual(stream, "slack_jobs_dead_letter")
        self.assertEqual(entry["source_message_id"], "1-0")
        self.assertIn("terminal failure", entry["error"])
        self.assertEqual(redis.acked, [("slack_jobs", "ingestion", "1-0")])

    def test_repeated_dead_letter_attempt_is_deduplicated(self):
        handler = RecordingHandler(error=RuntimeError("terminal failure"))
        redis = FakeRedis(pending=[self.pending(deliveries=5)])
        consumer = self.make_consumer(redis, handler, max_deliveries=5)

        for _ in range(2):
            redis.pending = [self.pending(deliveries=5)]
            consumer._process_message("slack_jobs", "1-0", self.pending()["data"], handler)

        self.assertEqual(len(redis.dead_letters), 1)

    def test_missing_and_default_tenant_jobs_are_rejected_and_dead_lettered(self):
        for tenant in ("", "default"):
            with self.subTest(tenant=tenant):
                raw = self.message(tenant)
                data = {"data": json.dumps(raw)}
                redis = FakeRedis(pending=[self.pending(deliveries=5, company_id=tenant)])
                consumer = self.make_consumer(redis, RecordingHandler(), max_deliveries=5)

                consumer._process_message("slack_jobs", "1-0", data, RecordingHandler())

                self.assertEqual(len(redis.dead_letters), 1)
                self.assertEqual(redis.acked, [("slack_jobs", "ingestion", "1-0")])

    def test_retry_after_database_side_effect_is_idempotent(self):
        handler = IdempotentSideEffectHandler()
        redis = FakeRedis(pending=[self.pending(deliveries=1)])
        consumer = self.make_consumer(redis, handler, max_deliveries=3)
        data = self.pending()["data"]

        consumer._process_message("slack_jobs", "1-0", data, handler)
        redis.pending.append(self.pending(deliveries=2))
        consumer._process_message("slack_jobs", "1-0", data, handler)

        self.assertEqual(handler.calls, 2)
        self.assertEqual(len(handler.effects), 1)
        self.assertEqual(redis.acked, [("slack_jobs", "ingestion", "1-0")])

    def test_redis_recovery_error_is_visible(self):
        redis = FakeRedis(reclaim_error=ConnectionError("redis unavailable"))
        consumer = self.make_consumer(redis, RecordingHandler())

        with self.assertRaisesRegex(RuntimeError, "pending-message inspection failed"):
            consumer._recover_pending()

    def test_stop_signals_blocked_consumer_loop(self):
        redis = FakeRedis()
        consumer = self.make_consumer(redis, RecordingHandler())
        consumer.running = True
        consumer.stop()

        self.assertFalse(consumer.running)
        self.assertTrue(consumer._stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
