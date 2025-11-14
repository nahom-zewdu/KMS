# nlp/utils/db_helpers.py
"""
Database helper functions for inserting entities, relations, and raw data into Supabase.
"""

import uuid
import logging
from typing import List, Dict, Any
from supabase import Client

logger = logging.getLogger("nlp.db_helpers")

def _ensure_uuid(val: str) -> str:
    try:
        if not val:
            return str(uuid.uuid4())
        # if already uuid-like, keep it
        return val
    except Exception:
        return str(uuid.uuid4())

def insert_entities(supabase: Client, entities: List[Dict[str, Any]]) -> None:
    """
    Insert or upsert entities into public.entities.
    Each entity dict expected to have fields matching to_db_record() output (without id or with id).
    Use upsert on id to avoid duplicate-key errors.
    """
    if not entities:
        return

    payload = []
    for e in entities:
        rec = dict(e)  # copy
        # ensure id
        rec_id = rec.get("id") or _ensure_uuid(None)
        rec["id"] = rec_id
        # ensure created_at exists
        if not rec.get("created_at"):
            rec["created_at"] = None
        payload.append(rec)

    try:
        # upsert on id — will insert new rows and update existing ones
        res = supabase.table("entities").upsert(payload, on_conflict="id").execute()
        logger.info("Inserted/upserted %d entities", len(payload))
        return res
    except Exception as e:
        # Fallback: try insert ignoring conflicts (safest)
        logger.exception("Upsert entities failed, attempting individual inserts: %s", e)
        for rec in payload:
            try:
                supabase.table("entities").insert(rec).execute()
            except Exception as ie:
                logger.warning("Single entity insert failed (likely duplicate): %s", ie)
        return

def insert_relations(supabase: Client, relations: List[Dict[str, Any]]) -> None:
    """
    Insert relations into public.edges.
    Each relation should already include 'created_at' and 'record_id'.
    Use upsert to avoid duplicate key errors if you have a natural id; otherwise, simple insert.
    """
    if not relations:
        return

    payload = []
    for r in relations:
        rec = dict(r)
        # If you have an 'id' field, ensure it's uuid. Otherwise let DB generate it if allowed.
        if not rec.get("id"):
            rec["id"] = str(uuid.uuid4())
        payload.append(rec)

    try:
        res = supabase.table("edges").upsert(payload, on_conflict="id").execute()
        logger.info("Inserted/upserted %d relations", len(payload))
        return res
    except Exception as e:
        logger.exception("Upsert relations failed, attempting batch insert fallback: %s", e)
        try:
            supabase.table("edges").insert(payload).execute()
        except Exception as ie:
            logger.exception("Batch insert relations failed: %s", ie)
        return

def insert_raw_data(supabase: Client, raw_record: Dict[str, Any]) -> None:
    """
    Safe insert for raw_data. Uses upsert on id if present; otherwise generate id.
    raw_record fields: id (optional), source, content, record_id, event_id (optional), created_at
    """
    rec = dict(raw_record)
    if not rec.get("id"):
        rec["id"] = str(uuid.uuid4())
    try:
        supabase.table("raw_data").upsert(rec, on_conflict="id").execute()
        logger.info("Inserted/upserted raw_data id=%s", rec["id"])
    except Exception as e:
        logger.exception("Failed to insert raw_data: %s", e)
        try:
            supabase.table("raw_data").insert(rec).execute()
        except Exception as ie:
            logger.exception("raw_data insert fallback failed: %s", ie)

def mark_event_processed(supabase: Client, delivery_id: str) -> None:
    if not delivery_id:
        return
    try:
        supabase.table("events").update({"processed": True}).eq("delivery_id", delivery_id).execute()
        logger.info("Marked event processed for delivery_id=%s", delivery_id)
    except Exception:
        logger.exception("Failed to mark event processed: %s", delivery_id)
