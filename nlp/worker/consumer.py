# worker/consumer.py
"""
Redis stream consumer with exactly-once semantics.
"""
import time
import json
import logging
from typing import Dict, Callable
from redis import Redis
from redis.exceptions import ConnectionError, TimeoutError
from utils import init_redis, log_error

class RedisStreamConsumer:
    def __init__(self, streams: list, group: str, handlers: Dict[str, Callable]):
        self.streams = {s: "$" for s in streams}
        self.group = group
        self.handlers = handlers
        self.redis = init_redis()
        self.running = False

        for stream in streams:
            self._ensure_group(stream)

    def _ensure_group(self, stream: str):
        try:
            self.redis.xgroup_create(stream, self.group, id="$", mkstream=True)
            logging.info(f"Created consumer group '{self.group}' for '{stream}'")
        except self.redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                log_error(f"Failed to create group for {stream}: {e}")

    def start(self):
        self.running = True
        while self.running:
            try:
                messages = self.redis.xread(
                    streams=self.streams,
                    count=10,
                    block=1000
                )
                if not messages:
                    continue

                for stream, entries in messages:
                    handler = self.handlers.get(stream)
                    if not handler:
                        continue

                    for msg_id, data in entries:
                        if not self.running:
                            break
                        self._process_message(stream, msg_id, data, handler)

            except (ConnectionError, TimeoutError):
                log_error("Redis connection lost. Reconnecting...")
                time.sleep(1)
                self.redis = init_redis()
            except Exception as e:
                log_error(f"Unexpected error: {e}")
                time.sleep(1)

        logging.info("Consumer stopped.")

    def _process_message(self, stream: str, msg_id: str, data: dict, handler):
        raw = data.get("data")
        if not raw:
            self._ack(stream, msg_id)
            return

        try:
            payload = json.loads(raw)
            job = self._normalize_job(payload)
            if not job:
                self._ack(stream, msg_id)
                return

            handler.process(job, stream, msg_id, self.redis)
            self._ack(stream, msg_id)

        except Exception as e:
            log_error(f"Handler failed for {msg_id}: {e}")
            # Do NOT ack → retry

    def _normalize_job(self, raw: dict):
        try:
            return {
                "record_id": raw.get("RecordID") or raw.get("record_id", ""),
                "source": raw.get("Source") or raw.get("source", ""),
                "content": raw.get("Content") or raw.get("content", ""),
                "created_at": raw.get("CreatedAt") or raw.get("created_at", "")
            }
        except:
            return None

    def _ack(self, stream: str, msg_id: str):
        try:
            self.redis.xack(stream, self.group, msg_id)
            self.redis.xdel(stream, msg_id)
        except:
            pass

    def stop(self):
        self.running = False
