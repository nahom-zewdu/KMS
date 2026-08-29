# worker/consumer.py
"""
Redis stream consumer with exactly-once semantics.
Claims pending messages that have been idle for longer than a configurable threshold.
- Uses XREADGROUP to read messages from multiple streams.
- Uses XAUTOCLAIM to reclaim pending messages that have been idle for longer than the configured threshold.
- Acknowledges messages only after successful processing.
- If a message fails processing, it is not acknowledged and will be retried on the next read.
- Handles Redis connection errors and attempts to reconnect.
"""

import time
import json
import logging
import os
import socket
import uuid
from typing import Dict, Callable
from redis.exceptions import ConnectionError, TimeoutError, ResponseError

from utils import init_redis, log_error

logger = logging.getLogger("consumer")

class RedisStreamConsumer:
    def __init__(
        self,
        streams: list,
        group: str,
        handlers: Dict[str, Callable],
        pending_idle_timeout_ms: int = 60000,
    ):
        if pending_idle_timeout_ms < 0:
            raise ValueError("pending_idle_timeout_ms must be non-negative")

        self.streams = {s: ">" for s in streams}
        self.group = group
        self.handlers = handlers
        self.pending_idle_timeout_ms = pending_idle_timeout_ms
        self.consumer_name = (
            f"consumer-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex}"
        )
        self.redis = init_redis()
        self.running = False

        for stream in streams:
            self._ensure_group(stream)

    def _ensure_group(self, stream: str):
        try:
            self.redis.xgroup_create(stream, self.group, id="$", mkstream=True)
            logging.info(f"Created consumer group '{self.group}' for '{stream}'")
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                log_error(f"Failed to create group for {stream}: {e}")

    def start(self):
        self.running = True

        while self.running:
            try:
                self._recover_pending()
                messages = self.redis.xreadgroup(
                    groupname=self.group,
                    consumername=self.consumer_name,
                    streams=self.streams,
                    count=10,
                    block=2000
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

            except ResponseError as e:
                if "NOGROUP" in str(e):
                    for stream in self.streams.keys():
                        try:
                            logging.info(f"Group '{self.group}' missing for '{stream}', creating...")
                            self.redis.xgroup_create(stream, self.group, id="0", mkstream=True)
                        except ResponseError as e2:
                            if "BUSYGROUP" in str(e2):  # Group already exists — normal race condition
                                logging.info(f"Consumer group '{self.group}' already exists for '{stream}', ignoring...")
                            else:
                                log_error(f"Failed to create missing group '{self.group}' on '{stream}': {e2}")
                    continue  # Try reading again
                else:
                    raise  # real error

            except Exception as e:
                log_error(f"Unexpected error: {e}")
                time.sleep(1)

        logging.info("Consumer stopped.")

    def _recover_pending(self):
        """Claim only messages idle beyond the configured threshold."""
        for stream, handler in self.handlers.items():
            if stream not in self.streams:
                continue

            try:
                _, entries = self.redis.xautoclaim(
                    stream,
                    self.group,
                    self.consumer_name,
                    min_idle_time=self.pending_idle_timeout_ms,
                    start_id="0-0",
                    count=10,
                )
            except (ConnectionError, TimeoutError, ResponseError) as e:
                logger.error("Failed to reclaim pending messages from %s: %s", stream, e)
                raise RuntimeError(f"pending-message recovery failed for {stream}") from e

            for msg_id, data in entries:
                if not self.running:
                    return
                self._process_message(stream, msg_id, data, handler)


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
                "event_type": raw.get("EventType") or raw.get("event_type", ""),
                "payload": raw.get("Payload") or raw.get("payload", {}),
                "created_at": raw.get("CreatedAt") or raw.get("created_at", ""),
                "company_id": raw.get("CompanyID") or raw.get("company_id", ""),
            }
        except Exception:
            return None

    def _ack(self, stream: str, msg_id: str):
        try:
            self.redis.xack(stream, self.group, msg_id)
            self.redis.xdel(stream, msg_id)
        except:
            pass

    def stop(self):
        self.running = False
