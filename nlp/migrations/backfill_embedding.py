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

def fetch_unembedded(batch_size: int = 1000) -> List[dict]:
    """Fetch raw_data records without embeddings."""
    response = (
        supabase.table("raw_data")
        .select("id, content")
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

    while True:
        records = fetch_unembedded()
        if not records:
            break

        texts = [r["content"] for r in records]
        embeddings = embed_batch(texts)

        updates = [
            {
                "id": r["id"],
                "embedding": emb,
                "embedding_model": "all-MiniLM-L6-v2"
            }
            for r, emb in zip(records, embeddings)
        ]

        # Batch upsert
        supabase.table("raw_data").upsert(updates, on_conflict="id").execute()
        total_processed += len(updates)
        logger.info(f"Embedded {len(updates)} records (total: {total_processed})")

    logger.info(f"Backfill complete: {total_processed} records embedded.")

if __name__ == "__main__":
    main()