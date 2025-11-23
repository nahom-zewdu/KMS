# nlp/query_engine/decay.py
"""
Edge confidence decay and TTL management.

Runs on every ingestion:
- Boosts confidence when relation is re-confirmed
- Slowly decays old edges
- Auto-expires after 90 days of no activity
"""

import datetime
from datetime import timedelta
from supabase import Client
import logging

logger = logging.getLogger(__name__)

def update_edge_lifecycle(
    supabase: Client,
    source_id: str,
    target_id: str,
    edge_type: str,
    source_record_id: str
):
    """
    Update confidence and last_seen_at for an existing edge.
    Called from ingestion.py after successful RE.
    """
    try:
        # Find existing edge
        result = (
            supabase.table("edges")
            .select("id", "confidence", "last_seen_at")
            .eq("source_id", source_id)
            .eq("target_id", target_id)
            .eq("type", edge_type)
            .execute()
        )

        if not result.data:
            return  # New edge will be inserted with default 0.95

        edge = result.data[0]
        old_conf = edge.get("confidence", 0.95)
        last_seen = edge.get("last_seen_at")

        # Boost confidence if re-confirmed
        new_conf = min(0.99, old_conf + 0.08)

        # Extend expiration: 90 days from now
        expires_at = datetime.datetime.now(datetime.UTC) + timedelta(days=90)

        # Update
        supabase.table("edges").update({
            "confidence": new_conf,
            "last_seen_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "expires_at": expires_at.isoformat(),
            "source_record_id": source_record_id  # latest proof
        }).eq("id", edge["id"]).execute()

        logger.info(f"Edge refreshed | {edge_type} | conf: {old_conf:.2f} → {new_conf:.2f}")

    except Exception as e:
        logger.error(f"Edge lifecycle update failed: {e}")
