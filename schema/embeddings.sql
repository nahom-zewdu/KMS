-- nlp/migrations/001_query_engine_v2_fixed.sql
-- Purpose: Enable KMS Query Engine v2 (Fixed: IMMUTABLE index predicates)
-- Adds pgvector embeddings, edge confidence/lifecycle, and indexes
-- Fully backward compatible – no data loss
-- Fixes: Uses generated columns for immutable partial indexes

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

-- IMMUTABLE INDEX: Confidence (no WHERE needed – filter in queries)
create index if not exists edges_confidence_idx on edges (confidence);

-- IMMUTABLE PARTIAL INDEX: Expires (use generated column for safety)
alter table edges 
add column if not exists is_expired boolean generated always as (
    (expires_at is not null and expires_at < now())
) stored;

create index if not exists edges_is_expired_idx 
on edges (is_expired) where is_expired = false;  -- Only index non-expired (immutable boolean)

-- Clean up: Drop generated column if you want (optional, after testing)
-- alter table edges drop column if exists is_expired;
