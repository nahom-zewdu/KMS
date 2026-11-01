"""Redis Streams consumer with lease-protected recovery and bounded retries.

Delivery is at-least-once. Handlers must make database side effects idempotent.
"""

import asyncio
import inspect
import json
import logging
import os
import socket
import threading
import time
import uuid
from typing import Callable

from redis.exceptions import ConnectionError, ResponseError, TimeoutError

from utils import init_redis, log_error

logger = logging.getLogger("consumer")

_RENEW_LEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_LEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

_MOVE_TO_DEAD_LETTER = """
local existing = redis.call('GET', KEYS[1])
if existing then
  return existing
end
local id = redis.call('XADD', KEYS[2], '*', unpack(ARGV, 2))
redis.call('SET', KEYS[1], id, 'EX', ARGV[1])
return id
"""


class RedisStreamConsumer:
    def __init__(
        self,
        streams: list[str],
        group: str,
        handlers: dict[str, Callable],
        pending_idle_timeout_ms: int = 60000,
        lease_ttl_ms: int = 120000,
        max_deliveries: int = 5,
    ):
        if pending_idle_timeout_ms < 0:
            raise ValueError("pending_idle_timeout_ms must be non-negative")
        if lease_ttl_ms < 3000:
            raise ValueError("lease_ttl_ms must be at least 3000")
        if max_deliveries < 1:
            raise ValueError("max_deliveries must be positive")

        self.streams = {stream: ">" for stream in streams}
        self.group = group
        self.handlers = handlers
        self.pending_idle_timeout_ms = pending_idle_timeout_ms
        self.lease_ttl_ms = lease_ttl_ms
        self.max_deliveries = max_deliveries
        self.consumer_name = f"consumer-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex}"
        self.redis = init_redis()
        self.running = False
        self._stop_event = threading.Event()

        for stream in streams:
            self._ensure_group(stream)

    def _ensure_group(self, stream: str):
        try:
            # Start at the beginning so first-time groups do not skip existing entries.
            self.redis.xgroup_create(stream, self.group, id="0-0", mkstream=True)
            logger.info("Created consumer group %s for %s", self.group, stream)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise RuntimeError(f"failed to create consumer group for {stream}") from exc

    def start(self):
        self.running = True
        self._stop_event.clear()
        while self.running:
            try:
                self._recover_pending()
                if not self.running:
                    break
                messages = self.redis.xreadgroup(
                    groupname=self.group,
                    consumername=self.consumer_name,
                    streams=self.streams,
                    count=10,
                    block=2000,
                )
                for stream_value, entries in messages or []:
                    stream = self._decode(stream_value)
                    handler = self.handlers.get(stream)
                    if handler is None:
                        logger.error("No handler is registered for stream %s", stream)
                        continue
                    for msg_id_value, data in entries:
                        if not self.running:
                            break
                        self._process_message(stream, self._decode(msg_id_value), data, handler)
            except (ConnectionError, TimeoutError):
                log_error("Redis connection lost. Reconnecting...")
                self._stop_event.wait(1)
                if self.running:
                    self.redis = init_redis()
                    for stream in self.streams:
                        self._ensure_group(stream)
            except ResponseError as exc:
                if "NOGROUP" in str(exc):
                    for stream in self.streams:
                        self._ensure_group(stream)
                    continue
                logger.exception("Redis stream command failed")
                self._stop_event.wait(1)
            except Exception:
                logger.exception("Unexpected consumer loop failure")
                self._stop_event.wait(1)

        logger.info("Consumer stopped.")

    def _recover_pending(self):
        for stream, handler in self.handlers.items():
            if stream not in self.streams:
                continue
            cursor = "-"
            while self.running:
                try:
                    pending = self.redis.xpending_range(stream, self.group, cursor, "+", 100)
                except (ConnectionError, TimeoutError, ResponseError) as exc:
                    raise RuntimeError(f"pending-message inspection failed for {stream}") from exc
                if not pending:
                    break

                for item in pending:
                    msg_id = self._decode(item["message_id"])
                    idle_ms = int(item["time_since_delivered"])
                    cursor = f"({msg_id}"
                    retry_delay_ms = min(
                        300000,
                        self.pending_idle_timeout_ms
                        * (2 ** min(9, max(0, int(item["times_delivered"]) - 1))),
                    )
                    if idle_ms < retry_delay_ms:
                        continue
                    token = uuid.uuid4().hex
                    lease_key = self._lease_key(stream, msg_id)
                    if not self._acquire_lease(lease_key, token):
                        continue
                    try:
                        claimed = self.redis.xclaim(
                            stream,
                            self.group,
                            self.consumer_name,
                            min_idle_time=0,
                            message_ids=[msg_id],
                        )
                    except (ConnectionError, TimeoutError, ResponseError):
                        self._release_lease(lease_key, token)
                        raise
                    for claimed_id, data in claimed or []:
                        self._process_message(
                            stream, self._decode(claimed_id), data, handler,
                            lease_token=token,
                        )
                if len(pending) < 100:
                    break

    def _process_message(self, stream: str, msg_id: str, data: dict, handler, lease_token=None):
        lease_key = self._lease_key(stream, msg_id)
        token = lease_token or uuid.uuid4().hex
        if lease_token is None and not self._acquire_lease(lease_key, token):
            logger.info("Job %s/%s is protected by another worker lease", stream, msg_id)
            return

        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(lease_key, token, heartbeat_stop, lease_lost),
            name=f"lease-{msg_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            raw = data.get("data") or data.get(b"data")
            if not raw:
                raise ValueError("stream entry is missing its data field")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            job = self._normalize_job(payload)

            if inspect.iscoroutinefunction(handler.process):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(handler.process(job, stream, msg_id, self.redis))
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)
            else:
                handler.process(job, stream, msg_id, self.redis)

            if lease_lost.is_set():
                raise RuntimeError("worker lost its processing lease; refusing to acknowledge")
            self._ack(stream, msg_id)
        except Exception as exc:
            logger.exception("Handler failed for %s/%s", stream, msg_id)
            try:
                deliveries = self._delivery_count(stream, msg_id)
                if deliveries >= self.max_deliveries:
                    self._dead_letter(stream, msg_id, data, exc, deliveries)
            except Exception:
                logger.exception("Failed to account for or dead-letter %s/%s", stream, msg_id)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=max(1.0, self.lease_ttl_ms / 1000))
            self._release_lease(lease_key, token)

    def _normalize_job(self, raw: dict) -> dict:
        if not isinstance(raw, dict):
            raise ValueError("stream job must be a JSON object")
        company_id = str(raw.get("CompanyID") or raw.get("company_id") or "").strip()
        if not company_id or company_id.lower() == "default":
            raise ValueError("job requires a real company_id")
        record_id = str(raw.get("RecordID") or raw.get("record_id") or "").strip()
        if not record_id:
            raise ValueError("job requires a record_id")
        payload = raw.get("Payload") if "Payload" in raw else raw.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("job payload must be a JSON object")
        return {
            "record_id": record_id,
            "source": raw.get("Source") or raw.get("source", ""),
            "content": raw.get("Content") or raw.get("content", ""),
            "event_type": raw.get("EventType") or raw.get("event_type", ""),
            "payload": payload,
            "created_at": raw.get("CreatedAt") or raw.get("created_at", ""),
            "company_id": company_id,
        }

    def _delivery_count(self, stream: str, msg_id: str) -> int:
        rows = self.redis.xpending_range(stream, self.group, msg_id, msg_id, 1)
        if not rows:
            return 0
        return int(rows[0]["times_delivered"])

    def _dead_letter(self, stream: str, msg_id: str, data: dict, error: Exception, deliveries: int):
        raw_data = data.get("data") or data.get(b"data") or ""
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode("utf-8", errors="replace")
        try:
            decoded = json.loads(raw_data) if raw_data else {}
        except json.JSONDecodeError:
            decoded = {}
        company_id = ""
        if isinstance(decoded, dict):
            company_id = str(decoded.get("CompanyID") or decoded.get("company_id") or "").strip()
        dead_letter = {
            "data": raw_data,
            "source_stream": stream,
            "source_message_id": msg_id,
            "company_id": company_id,
            "deliveries": str(deliveries),
            "error": str(error)[:1000],
            "failed_at": str(time.time()),
        }
        dedupe_key = f"kms:dead-letter:{self.group}:{stream}:{msg_id}"
        fields = []
        for key, value in dead_letter.items():
            fields.extend((key, value))
        self.redis.eval(
            _MOVE_TO_DEAD_LETTER,
            2,
            dedupe_key,
            f"{stream}_dead_letter",
            90 * 24 * 60 * 60,
            *fields,
        )
        self._ack(stream, msg_id)
        logger.error("Moved exhausted job %s/%s to dead-letter stream", stream, msg_id)

    def _ack(self, stream: str, msg_id: str):
        self.redis.xack(stream, self.group, msg_id)

    def _lease_key(self, stream: str, msg_id: str) -> str:
        return f"kms:worker-lease:{self.group}:{stream}:{msg_id}"

    def _acquire_lease(self, key: str, token: str) -> bool:
        return bool(self.redis.set(key, token, nx=True, px=self.lease_ttl_ms))

    def _heartbeat(self, key: str, token: str, stop_event: threading.Event, lease_lost: threading.Event):
        interval = max(1.0, self.lease_ttl_ms / 3000)
        while not stop_event.wait(interval):
            try:
                renewed = self.redis.eval(_RENEW_LEASE, 1, key, token, self.lease_ttl_ms)
                if int(renewed or 0) != 1:
                    lease_lost.set()
                    return
            except Exception:
                logger.exception("Failed to renew worker lease %s", key)
                lease_lost.set()
                return

    def _release_lease(self, key: str, token: str):
        try:
            self.redis.eval(_RELEASE_LEASE, 1, key, token)
        except Exception:
            logger.exception("Failed to release worker lease %s; it will expire", key)

    @staticmethod
    def _decode(value):
        return value.decode("utf-8") if isinstance(value, bytes) else value

    def stop(self):
        self.running = False
        self._stop_event.set()
