# worker/ingestion.py
"""
Handles slack_jobs/github_jobs → NER → RE → Supabase.
"""

import time
import logging
from datetime import datetime, timezone

from utils.common import log_error
from utils.supabase import init_supabase
from engine.re import extract_relations
from engine.ner import extract_entities

from utils.db_helpers import (
    insert_entities,
    insert_relations,
    insert_raw_data,
    mark_event_processed,
)

supabase = init_supabase()

class IngestionHandler:
    def process(self, job: dict, stream: str, msg_id: str, redis_client):
        start = time.time()
        logging.info(f"Processing ingestion | {job['record_id']} | {job['source']}")

        try:
            created_at = job["created_at"] or datetime.now(timezone.utc).isoformat()

            # NER
            entities = extract_entities(
                text=job["content"],
                record_id=job["record_id"],
                source=job["source"],
                created_at=created_at,
            )

            entity_dicts = [e.dict() for e in entities]

            # RE
            relations = extract_relations(
                text=job["content"],
                entities=entity_dicts,
                record_id=job["record_id"],
                created_at=created_at,
            )

            # Insert raw_data first
            insert_raw_data(
                supabase,
                {
                    "record_id": job["record_id"],
                    "source": job["source"],
                    "content": job["content"],
                    "event_id": job.get("event_id"),
                    "created_at": created_at,
                },
            )

            # Entities
            if entities:
                db_entities = [e.to_db_record() for e in entities]
                insert_entities(supabase, db_entities)
                logging.info(f"Inserted {len(db_entities)} entities")

            # Relations
            if relations:
                insert_relations(supabase, relations)
                logging.info(f"Inserted {len(relations)} relations")

            # Mark event processed
            mark_event_processed(supabase, job["record_id"])

            logging.info(f"Ingestion complete in {time.time()-start:.3f}s")

        except Exception as e:
            log_error(f"Ingestion failed: {e}")
            raise
