# nlp/main.py
"""
Main orchestration loop for the KMS NLP Processor.

Responsibilities:
1. Consume from Redis streams: slack_jobs, github_jobs, query_jobs
2. Route to correct handler with full context
3. Enforce idempotency and exactly-once processing
4. Structured logging, metrics, error handling
5. Graceful shutdown and health checks

Design Principles:
- Zero message loss
- Exactly-once semantics via XACK + XDEL
- Fail-fast on malformed input
- Full observability
- Minimal latency
- LLM-powered NER/RE via engine/
"""

import json
import os
import time
import signal
import logging
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import contextmanager

from dotenv import load_dotenv
from redis import Redis
from redis.exceptions import ConnectionError, TimeoutError

from utils import init_supabase, init_redis, log_error, setup_structured_logging
from nlp.engine.ner import extract_entities as llm_extract_entities
from nlp.engine.re import extract_relations as llm_extract_relations
from nlp.query_handler import handle_query

# === CONFIGURATION ===
load_dotenv()

REDIS_ADDR = os.getenv("REDIS_ADDR")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
STREAMS = {"slack_jobs": "$", "github_jobs": "$", "query_jobs": "$"}
CONSUMER_GROUP = "kms"
BATCH_SIZE = 10
BLOCK_MS = 1000
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 0.1  # seconds

# === GLOBALS ===
redis: Redis = init_redis(REDIS_ADDR, REDIS_PASSWORD)
supabase = init_supabase()
shutdown_event = threading.Event()


# === DATA MODEL ===
@dataclass
class Job:
    """Normalized job from Redis stream."""
    record_id: str
    source: str
    event_type: str
    content: str
    payload: Dict[str, Any]
    created_at: str

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> Optional["Job"]:
        """Safely construct Job from raw Redis payload."""
        try:
            return cls(
                record_id=raw.get("RecordID") or raw.get("record_id", ""),
                source=raw.get("Source") or raw.get("source", ""),
                event_type=raw.get("EventType") or raw.get("event_type", ""),
                content=raw.get("Content") or raw.get("content", ""),
                payload=raw.get("Payload") or raw.get("payload", {}),
                created_at=raw.get("CreatedAt") or raw.get("created_at", "")
            )
        except Exception as e:
            log_error(f"Failed to parse job: {e} | Raw: {raw}")
            return None


# === HEALTH & GRACEFUL SHUTDOWN ===
def signal_handler(signum, frame):
    logging.info("Shutdown signal received. Draining...")
    shutdown_event.set()

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


@contextmanager
def redis_connection():
    """Context manager for Redis with auto-reconnect."""
    try:
        yield redis
    except (ConnectionError, TimeoutError) as e:
        log_error(f"Redis connection lost: {e}. Reconnecting...")
        global redis
        redis = init_redis(REDIS_ADDR, REDIS_PASSWORD)
        raise


# === STREAM PROCESSING CORE ===
def ensure_consumer_group(stream: str):
    """Create consumer group if not exists."""
    try:
        redis.xgroup_create(stream, CONSUMER_GROUP, id="$", mkstream=True)
        logging.info(f"Created consumer group '{CONSUMER_GROUP}' for stream '{stream}'")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            log_error(f"Failed to create consumer group for {stream}: {e}")


def process_ingestion_job(job: Job, message_id: str, stream_name: str):
    """
    Process slack_jobs or github_jobs → NER → RE → Supabase.
    Exactly-once via XACK + XDEL.
    """
    start = time.time()
    logging.info(f"Processing ingestion | RecordID: {job.record_id} | Source: {job.source} | Stream: {stream_name}")

    try:
        # === 1. NER ===
        entities = llm_extract_entities(
            text=job.content,
            record_id=job.record_id,
            source=job.source,
            created_at=job.created_at or datetime.now(timezone.utc).isoformat()
        )

        # === 2. RE ===
        relations = llm_extract_relations(
            text=job.content,
            entities=entities,
            record_id=job.record_id,
            created_at=job.created_at or datetime.now(timezone.utc).isoformat()
        )

        # === 3. Persist to Supabase ===
        if entities:
            entity_data = [e.dict() for e in entities]
            supabase.table("entities").insert(entity_data).execute()
            logging.info(f"Inserted {len(entities)} entities")

        if relations:
            relation_data = [r.dict() for r in relations]
            supabase.table("edges").insert(relation_data).execute()
            logging.info(f"Inserted {len(relations)} relations")

        # === 4. Mark event as processed ===
        supabase.table("events").update({"processed": True}) \
            .eq("delivery_id", job.record_id).execute()

        # === 5. Acknowledge ===
        redis.xack(stream_name, CONSUMER_GROUP, message_id)
        redis.xdel(stream_name, message_id)
        logging.info(f"Completed ingestion in {time.time() - start:.3f}s")

    except Exception as e:
        log_error(f"Failed to process ingestion job {job.record_id}: {e}")
        # Do NOT ack → retry later
        raise


def process_query_job(job: Job):
    """Route query_jobs to LLM answer generation."""
    handle_query(job, supabase, redis)


# === MAIN LOOP ===
def main():
    """Main processing loop with batching, retry, and shutdown handling."""
    setup_structured_logging()
    logging.info("KMS NLP Processor starting...")

    # Ensure consumer groups
    for stream in STREAMS.keys():
        ensure_consumer_group(stream)

    while not shutdown_event.is_set():
        try:
            with redis_connection() as r:
                response = r.xread(
                    streams=STREAMS,
                    count=BATCH_SIZE,
                    block=BLOCK_MS
                )

            if not response:
                continue

            for stream_name, messages in response:
                for message_id, message_data in messages:
                    if shutdown_event.is_set():
                        break

                    # === Parse raw message ===
                    raw_data = message_data.get("data")
                    if not raw_data:
                        logging.warning(f"Empty data in {message_id} from {stream_name}")
                        r.xack(stream_name, CONSUMER_GROUP, message_id)
                        r.xdel(stream_name, message_id)
                        continue

                    try:
                        payload = json.loads(raw_data)
                    except json.JSONDecodeError as e:
                        log_error(f"Invalid JSON in {message_id}: {e}")
                        r.xack(stream_name, CONSUMER_GROUP, message_id)
                        r.xdel(stream_name, message_id)
                        continue

                    job = Job.from_raw(payload)
                    if not job or not job.record_id or not job.content.strip():
                        logging.warning(f"Invalid job, skipping: {payload}")
                        r.xack(stream_name, CONSUMER_GROUP, message_id)
                        r.xdel(stream_name, message_id)
                        continue

                    # === Route to handler ===
                    try:
                        if stream_name == "query_jobs":
                            process_query_job(job)
                            r.xack(stream_name, CONSUMER_GROUP, message_id)
                            r.xdel(stream_name, CONSUMER_GROUP, message_id)
                        else:
                            process_ingestion_job(job, message_id, stream_name)
                    except Exception as e:
                        # Only log — do NOT ack → retry
                        log_error(f"Handler failed for {job.record_id}: {e}")

        except (ConnectionError, TimeoutError):
            time.sleep(1)
            continue
        except Exception as e:
            log_error(f"Unexpected error in main loop: {e}")
            time.sleep(1)

    logging.info("KMS NLP Processor shut down gracefully.")


if __name__ == "__main__":
    main()
    