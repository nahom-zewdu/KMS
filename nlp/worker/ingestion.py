# worker/ingestion.py
"""
Handles slack_jobs/github_jobs → NER → RE → Supabase + Codebase Analysis.
For GitHub push events, publishes a durable codebase analysis job to Redis stream.
This ensures codebase analysis failures are observable and retryable (no detached threads).
"""

import time
import logging
import json
import uuid
from datetime import datetime, timezone

from utils.common import log_error
from utils.supabase import init_supabase
from utils import init_redis
from engine.re import extract_relations
from engine.ner import extract_entities
from engine.schema import Entity, deterministic_edge_id
from utils.db_helpers import (
    ensure_event_tenant,
    insert_entities,
    insert_relations,
    insert_raw_data,
    mark_event_processed,
)

logger = logging.getLogger("ingestion")
supabase = init_supabase()
redis_client = init_redis()


class IngestionHandler:
    """Handles event ingestion with NER/RE. Delegates codebase analysis to separate stream."""

    def process(self, job: dict, stream: str, msg_id: str, redis_client):
        start = time.time()
        logging.info(f"Processing ingestion | {job.get('record_id')} | {job.get('source')}")

        try:
            self._process_sync(job, redis_client)
            logging.info(f"Ingestion complete in {time.time()-start:.3f}s")

        except Exception as e:
            log_error(f"Ingestion failed: {e}")
            raise

    def _process_sync(self, job: dict, stream_redis=None):
        record_id = job.get("record_id")
        source = job.get("source", "")
        event_type = job.get("event_type", "")
        content = job.get("content", "")
        payload = job.get("payload", {})
        company_id = (job.get("company_id") or "").strip()
        if not company_id or company_id.lower() == "default":
            raise ValueError("a real company_id is required for ingestion")
        if not record_id:
            raise ValueError("record_id is required for ingestion")
        if source not in ("slack", "github"):
            raise ValueError("source must be slack or github")
        ensure_event_tenant(supabase, record_id, company_id)

        created_at = job.get("created_at") or datetime.now(timezone.utc).isoformat()

        # 1. NER (NO FILES HERE)
        entities = extract_entities(
            text=content,
            record_id=record_id,
            source=source,
            created_at=created_at,
        )

        if not entities:
            insert_raw_data(supabase, {
                "record_id": record_id,
                "source": source,
                "content": content,
                "company_id": company_id,
                "created_at": created_at,
            })
            if source == "github" and event_type == "push":
                self._publish_codebase_analysis_job(job, stream_redis or redis_client)
            mark_event_processed(supabase, record_id, company_id)
            return

        # 2. Insert NER Entities
        db_entities = [e.to_db_record() for e in entities]
        for e in db_entities:
            e["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nlp-entity:{company_id}:{e['id']}"))
            e["company_id"] = company_id
            meta = e.get("metadata") or {}
            meta["company_id"] = company_id
            e["metadata"] = meta
        insert_entities(supabase, db_entities)

        entity_text_to_id = {
            e["name"].lower(): e["id"]
            for e in db_entities
        }

        # 3. RE (only semantic entities)
        entity_dicts = [e.model_dump() for e in entities]

        raw_relations = extract_relations(
            text=content,
            entities=entity_dicts,
            record_id=record_id,
            created_at=created_at,
        )

        relations_payload = []
        for r in raw_relations:
            src_id = entity_text_to_id.get(r["source"])
            tgt_id = entity_text_to_id.get(r["target"])

            if not src_id or not tgt_id:
                continue

            relations_payload.append({
                "id": deterministic_edge_id(src_id, tgt_id, r["type"]),
                "source_id": src_id,
                "target_id": tgt_id,
                "type": r["type"],
                "confidence": 0.95,
                "source_record_id": record_id,
                "company_id": company_id,
                "created_at": r.get("created_at") or created_at,
            })

        if relations_payload:
            insert_relations(supabase, relations_payload)

        # 4. Raw ingestion record
        insert_raw_data(supabase, {
            "record_id": record_id,
            "source": source,
            "content": content,
            "company_id": company_id,
            "created_at": created_at,
        })

        if source == "github" and event_type == "push":
            logging.info("Publishing codebase analysis job for GitHub push")
            self._publish_codebase_analysis_job(job, stream_redis or redis_client)
        mark_event_processed(supabase, record_id, company_id)

    def _publish_codebase_analysis_job(self, job: dict, stream_redis):
        """
        Publish a codebase analysis job to the Redis stream.
        This replaces the previous detached daemon thread approach.
        Ensures the job is durable and failures are observable/retryable.
        """
        try:
            # Prepare the job payload for codebase analysis stream
            analysis_job = {
                "RecordID": job.get("record_id"),
                "Source": "github",
                "EventType": job.get("event_type"),
                "Payload": job.get("payload", {}),
                "CompanyID": job.get("company_id"),
                "CreatedAt": job.get("created_at") or datetime.now(timezone.utc).isoformat(),
            }
            
            # Publish to the durable codebase analysis stream
            stream_redis.xadd(
                "codebase_analysis_jobs",
                {"data": json.dumps(analysis_job)},
            )
            
            logging.info(f"Codebase analysis job published | record_id={job.get('record_id')}")
        except Exception as e:
            log_error(f"Failed to publish codebase analysis job: {e}")
            raise
