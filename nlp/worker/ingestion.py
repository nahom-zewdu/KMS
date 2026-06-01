# worker/ingestion.py
"""
Handles slack_jobs/github_jobs → NER → RE → Supabase + Codebase Analysis.
- For GitHub push events, it also triggers the CodebaseAnalyzer to extract file-level entities and relationships.
- Uses a mix of sync and async processing to balance simplicity and performance.
"""

import time
import logging
from datetime import datetime, timezone
import asyncio
import threading
from utils.common import log_error
from utils.supabase import init_supabase
from engine.re import extract_relations
from engine.ner import extract_entities
from codebase.analyzer import CodebaseAnalyzer
from utils.db_helpers import (
    insert_entities,
    insert_relations,
    insert_raw_data,
    mark_event_processed,
)

logger = logging.getLogger("ingestion")
supabase = init_supabase()

class IngestionHandler:
    def __init__(self):
        self.codebase_analyzer = CodebaseAnalyzer(supabase)

    def process(self, job: dict, stream: str, msg_id: str, redis_client):
        start = time.time()
        logging.info(f"Processing ingestion | {job.get('record_id')} | {job.get('source')}")

        try:
            self._process_sync(job)
            logging.info(f"Ingestion complete in {time.time()-start:.3f}s")

        except Exception as e:
            log_error(f"Ingestion failed: {e}")
            raise

    def _process_sync(self, job: dict):
        """Main processing logic (kept sync where possible)."""
        record_id = job.get("record_id", None)
        source = job.get("source", "")
        event_type = job.get("event_type", "")
        event_id = job.get("event_id", None)
        content = job.get("content", "")
        payload = job.get("payload", {})

        logger.info(f"Processing ingestion | {record_id} | {source}")

        created_at = job.get("created_at") or datetime.now(timezone.utc).isoformat()

        # --- NER ---
        entities = extract_entities(
            text=content,
            record_id=record_id,
            source=source,
            created_at=created_at,
        )

        if not entities:
            logging.info("No entities found, skipping RE.")
            insert_raw_data(supabase, {
                "record_id": record_id,
                "source": source,
                "content": content,
                "event_id": event_id,
                "created_at": created_at,
            })
            mark_event_processed(supabase, record_id)
            return

        # --- Insert Entities ---
        db_entities = [e.to_db_record() for e in entities]
        insert_entities(supabase, db_entities)

        # --- Build text -> ID mapping ---
        entity_text_to_id = {e['name'].lower(): e['id'] for e in db_entities}

        # --- RE ---
        entity_dicts = [e.dict() for e in entities]
        raw_relations = extract_relations(
            text=content,
            entities=entity_dicts,
            record_id=record_id,
            created_at=created_at,
        )

        # --- Map relations ---
        relations_payload = []
        for r in raw_relations:
            src_id = entity_text_to_id.get(r['source'])
            tgt_id = entity_text_to_id.get(r['target'])
            if not src_id or not tgt_id:
                continue
            relations_payload.append({
                "source_id": src_id,
                "target_id": tgt_id,
                "type": r['type'],
                "created_at": r.get("created_at") or created_at
            })

        if relations_payload:
            insert_relations(supabase, relations_payload)

        # --- Insert raw data ---
        insert_raw_data(supabase, {
            "record_id": record_id,
            "source": source,
            "content": content,
            "event_id": event_id,
            "created_at": created_at,
        })

        # --- Mark processed ---
        mark_event_processed(supabase, record_id)

        # --- Codebase Analysis (GitHub Push Only) ---
        if source == "github" and event_type == "push":
            logging.info("Starting codebase analysis for GitHub push")
            def run_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(
                        self.codebase_analyzer.process_push_event(
                            payload, 
                            record_id
                        )
                    )
                except Exception as e:
                    logger.error(f"Codebase analysis failed: {e}")
                finally:
                    loop.close()

            thread = threading.Thread(target=run_async, daemon=True)
            thread.start()
