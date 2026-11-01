# nlp/utils/db_helpers.py
"""
Database helper functions for inserting entities, relations, and raw data into Supabase.
"""

import uuid
import logging
from typing import List, Dict, Any
from supabase import Client
from sentence_transformers import SentenceTransformer
from functools import lru_cache

logger = logging.getLogger("nlp.db_helpers")


@lru_cache(maxsize=1)
def get_embedder():
    """Singleton embedder loads once, reuses."""
    return SentenceTransformer('all-MiniLM-L6-v2')

def embed_content(content: str) -> list:
    """Generate 384-dim embedding."""
    return get_embedder().encode(content, normalize_embeddings=True).tolist()

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
        res = supabase.table("entities").upsert(payload, on_conflict="id").execute()
    except Exception as exc:
        logger.exception("Entity upsert failed")
        raise RuntimeError("entity persistence failed") from exc
    logger.info("Inserted/upserted %d entities", len(payload))
    return res

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
    except Exception as exc:
        logger.exception("Relation upsert failed")
        raise RuntimeError("relation persistence failed") from exc
    logger.info("Inserted/upserted %d relations", len(payload))
    return res

def insert_raw_data(supabase: Client, raw_job: Dict[str, Any]) -> None:
    """
    Safe insert for raw_data with automatic embedding generation.
    This is the ONLY place embeddings are created at ingestion time.
    """
    rec = dict(raw_job)  # defensive copy
    record_id = str(rec.get("record_id") or "").strip()
    company_id = str(rec.get("company_id") or "").strip()
    if not record_id:
        raise ValueError("record_id is required for raw_data persistence")
    if not company_id or company_id.lower() == "default":
        raise ValueError("a real company_id is required for raw_data persistence")

    existing = (
        supabase.table("raw_data")
        .select("id,company_id")
        .eq("record_id", record_id)
        .eq("company_id", company_id)
        .limit(2)
        .execute()
    )
    existing_rows = getattr(existing, "data", []) or []
    if len(existing_rows) > 1:
        raise RuntimeError(f"raw_data record_id {record_id} is not unique")

    content = rec.get("content", "").strip()

    # Generate embedding
    if content:
        try:
            rec["embedding"] = embed_content(content)
            rec["embedding_model"] = "all-MiniLM-L6-v2"
        except Exception as e:
            raise RuntimeError("embedding generation failed") from e
    else:
        rec["embedding"] = None

    # === CRITICAL: Robust ID handling ===
    if not rec.get("id") or str(rec.get("id")).strip() in ("", "[]", "null", "None"):
        rec["id"] = str(uuid.uuid4())

    # Ensure record_id exists and is valid (used for business uniqueness)
    if not rec.get("record_id"):
        rec["record_id"] = rec["id"]  # fallback

    if existing_rows:
        rec.pop("id", None)
        try:
            response = (
                supabase.table("raw_data")
                .update(rec)
                .eq("record_id", record_id)
                .eq("company_id", company_id)
                .select("id")
                .execute()
            )
            if not (getattr(response, "data", None) or []):
                raise ValueError("tenant-scoped raw_data update matched no row")
        except Exception as exc:
            logger.exception("Tenant-scoped raw_data update failed for record_id=%s", record_id)
            raise RuntimeError("raw_data persistence failed") from exc
        logger.info("Updated raw_data + embedding | record_id=%s", record_id)
        return
    try:
        supabase.table("raw_data").insert(rec).execute()
        logger.info("Inserted raw_data + embedding | record_id=%s", record_id)
    except Exception as exc:
        logger.exception("raw_data insert failed for record_id=%s", record_id)
        raise RuntimeError("raw_data persistence failed") from exc


def ensure_event_tenant(supabase: Client, delivery_id: str, company_id: str) -> None:
    if not delivery_id or not company_id or company_id.strip().lower() == "default":
        raise ValueError("real event delivery and company IDs are required")
    try:
        response = (
            supabase.table("events")
            .select("delivery_id,company_id")
            .eq("delivery_id", delivery_id)
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.exception("Event tenant validation query failed for delivery_id=%s", delivery_id)
        raise RuntimeError("event tenant validation failed") from exc
    rows = getattr(response, "data", []) or []
    if not rows:
        raise ValueError("event delivery does not belong to the job company")


def mark_event_processed(supabase: Client, delivery_id: str, company_id: str) -> None:
    if not delivery_id or not company_id or company_id.strip().lower() == "default":
        raise ValueError("real event delivery and company IDs are required")
    try:
        response = (
            supabase.table("events")
            .update({"processed": True})
            .eq("delivery_id", delivery_id)
            .eq("company_id", company_id)
            .select("delivery_id")
            .execute()
        )
        if not (getattr(response, "data", None) or []):
            raise ValueError("event processing marker matched no company-owned event")
        logger.info("Marked event processed for delivery_id=%s", delivery_id)
    except Exception as exc:
        logger.exception("Failed to mark event processed: %s", delivery_id)
        raise RuntimeError("event processed marker update failed") from exc
