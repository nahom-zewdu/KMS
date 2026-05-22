-- nlp/migrations/001_query_engine_v2_final.sql
-- Purpose: Enable KMS Query Engine v2 (Fixed: IMMUTABLE generated column)
-- Adds pgvector embeddings, edge confidence/lifecycle, and indexes
-- Fully backward compatible – no data loss
-- Changes: Removed generated 'is_expired' column (uses now() – not immutable)
--          Filter expiration in queries instead (WHERE expires_at > now())

-- Enable pgvector extension (safe to run multiple times)
create extension if not exists vector with schema extensions;

-- Add embedding column + model tracking to raw_data
alter table raw_data 
add column if not exists embedding vector(384),
add column if not exists embedding_model text default 'all-MiniLM-L6-v2';

-- High-performance HNSW index for vector search
create index if not exists raw_data_embedding_idx 
on raw_data using hnsw (embedding vector_cosine_ops) 
with (m = 16, ef_construction = 64);

-- Edge confidence, lifecycle, and source tracing
alter table edges 
add column if not exists confidence double precision default 0.95 
    check (confidence >= 0 and confidence <= 1),
add column if not exists last_seen_at timestamptz default now(),
add column if not exists source_record_id text,  -- links back to raw_data.record_id
add column if not exists expires_at timestamptz;

-- Entity freshness tracking
alter table entities 
add column if not exists last_seen_at timestamptz default now();

-- IMMUTABLE INDEX: Confidence (no WHERE – filter in queries)
create index if not exists edges_confidence_idx on edges (confidence);

-- IMMUTABLE INDEX: Expires (simple index – filter with WHERE expires_at > now() in queries)
create index if not exists edges_expires_idx on edges (expires_at);
