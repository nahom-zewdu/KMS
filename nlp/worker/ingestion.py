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
            created_at = job.get("created_at") or datetime.now(timezone.utc).isoformat()

            # --- NER ---
            entities = extract_entities(
                text=job["content"],
                record_id=job["record_id"],
                source=job["source"],
                created_at=created_at,
            )

            if not entities:
                logging.info("No entities found, skipping RE.")
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
                mark_event_processed(supabase, job["record_id"])
                return

            # --- Insert Entities ---
            db_entities = [e.to_db_record() for e in entities]
            insert_entities(supabase, db_entities)
            logging.info(f"Inserted {len(db_entities)} entities")

            # --- Build text -> ID mapping ---
            entity_text_to_id = {e['name'].lower(): e['id'] for e in db_entities}

            # --- RE ---
            entity_dicts = [e.dict() for e in entities]
            raw_relations = extract_relations(
                text=job["content"],
                entities=entity_dicts,
                record_id=job["record_id"],
                created_at=created_at,
            )

            # --- Map relation text -> IDs ---
            relations_payload = []
            for r in raw_relations:
                src_id = entity_text_to_id.get(r['source'])
                tgt_id = entity_text_to_id.get(r['target'])

                if not src_id or not tgt_id:
                    logging.warning("Skipping relation; entity ID not found: %s", r)
                    continue

                relations_payload.append({
                    "source_id": src_id,
                    "target_id": tgt_id,
                    "type": r['type'],
                    "created_at": r.get("created_at") or created_at
                })

            # --- Insert relations ---
            if relations_payload:
                insert_relations(supabase, relations_payload)
                logging.info(f"Inserted {len(relations_payload)} relations")

            # --- Insert raw data ---
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

            # --- Mark event processed ---
            mark_event_processed(supabase, job["record_id"])
            logging.info(f"Ingestion complete in {time.time()-start:.3f}s")

        except Exception as e:
            log_error(f"Ingestion failed: {e}")
            raise
