# worker/ingestion.py
"""
Handles slack_jobs/github_jobs → NER → RE → Supabase.
"""
import logging
import time
from datetime import datetime, timezone
from engine.ner import extract_entities
from engine.re import extract_relations
from utils import init_supabase

supabase = init_supabase()

class IngestionHandler:
    def process(self, job: dict, stream: str, msg_id: str, redis_client):
        start = time.time()
        logging.info(f"Processing ingestion | {job['record_id']} | {job['source']}")

        try:
            entities = extract_entities(
                text=job["content"],
                record_id=job["record_id"],
                source=job["source"],
                created_at=job["created_at"] or datetime.now(timezone.utc).isoformat()
            )

            relations = extract_relations(
                text=job["content"],
                entities=entities,
                record_id=job["record_id"],
                created_at=job["created_at"] or datetime.now(timezone.utc).isoformat()
            )

            if entities:
                supabase.table("entities").insert([e.dict() for e in entities]).execute()
                logging.info(f"Inserted {len(entities)} entities")

            if relations:
                supabase.table("edges").insert([r.dict() for r in relations]).execute()
                logging.info(f"Inserted {len(relations)} relations")

            supabase.table("events").update({"processed": True}) \
                .eq("delivery_id", job["record_id"]).execute()

            logging.info(f"Ingestion complete in {time.time()-start:.3f}s")

        except Exception as e:
            log_error(f"Ingestion failed: {e}")
            raise
