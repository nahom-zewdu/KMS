# nlp/migrations/backfill_embeddings.py
"""
One-time script to generate embeddings for all existing raw_data records.
Uses all-MiniLM-L6-v2 (384-dim) – optimal balance of speed/quality.
Run once after migration.
"""

import os
import logging
from datetime import datetime
from typing import List
from supabase import create_client, Client
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize clients
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

# Load model once (thread-safe)
model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')  # GPU if available

BATCH_SIZE = 32

def fetch_unembedded(company_id: str, batch_size: int = 1000) -> List[dict]:
    """Fetch unembedded records for one explicitly selected company."""
    if not company_id or company_id.strip().lower() == "default":
        raise ValueError("A real company_id is required for embedding backfill")
    response = (
        supabase.table("raw_data")
        .select("id, company_id, content")
        .eq("company_id", company_id)
        .is_("embedding", None)
        .limit(batch_size)
        .execute()
    )
    return response.data

def embed_batch(texts: List[str]) -> List[list]:
    """Generate embeddings in batch."""
    return model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=False, normalize_embeddings=True).tolist()

def main():
    logger.info("Starting embedding backfill...")
    total_processed = 0

    companies = supabase.table("companies").select("id").execute().data or []
    for company in companies:
        company_id = str(company.get("id") or "").strip()
        if not company_id or company_id.lower() == "default":
            logger.error("Skipping invalid company identifier during embedding backfill")
            continue

        while True:
            records = fetch_unembedded(company_id)
            if not records:
                break

            texts = [r["content"] for r in records]
            embeddings = embed_batch(texts)

            updates = [
                {
                    "id": record["id"],
                    "company_id": company_id,
                    "embedding": embedding,
                    "embedding_model": "all-MiniLM-L6-v2",
                }
                for record, embedding in zip(records, embeddings)
            ]

            supabase.table("raw_data").upsert(updates, on_conflict="id").execute()
            total_processed += len(updates)
            logger.info("Embedded %d records for one company (total: %d)", len(updates), total_processed)

    logger.info(f"Backfill complete: {total_processed} records embedded.")

if __name__ == "__main__":
    main()