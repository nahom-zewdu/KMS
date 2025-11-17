# KMS System Design Overview (November 2025 — Production-Ready MVP)

## Introduction

**KMS** is an AI-powered knowledge oracle that passively captures tribal knowledge from Slack and GitHub, builds a real-time, referentially-integral knowledge graph, and delivers instant, accurate answers to questions like:

- “Who owns the billing service?”
- “What was the context when the payment retry logic was added?”
- “Which engineer has the most context on KMS-123?”

KMS eliminates onboarding friction, reduces repetitive questions, and mitigates bus-factor risk in engineering teams. The system is built for correctness, observability, and resilience — all while staying within free-tier limits of Supabase, Upstash Redis, and Groq.

Current status: End-to-end flow is stable and production-grade. Ingestion → KG construction → query loop works reliably with real Slack and GitHub events.

## Architecture Overview

```txt
Slack / GitHub Webhook
        ↓
   Go Backend (Gin + Vercel)
        ↓
   Supabase (raw events + raw_data) + Redis Streams (slack_jobs / github_jobs / query_jobs)
        ↓
   Python NLP Worker (Render)
        ↓
   NER → Entities (UUID) → RE → Edges (UUID-grounded)
        ↓
   Supabase Knowledge Graph
        ↓
   Query → (future: vector + graph search) → LLM → Answer → Slack Thread (Pub/Sub)
```

## Key Components

### 1. Ingestion Layer (Go Backend — `api/`)

- Secure webhook endpoints with signature verification
- Exactly-once semantics via `delivery_id` → `events` table check
- Stores raw payloads in `events`, summarized content in `raw_data`
- Publishes to source-specific Redis streams (`slack_jobs`, `github_jobs`)
- Slack bot publishes user queries to `query_jobs`
- Real-time response via Redis Pub/Sub (`query_results:{query_id}`)

### 2. Storage Layer (Supabase — Postgres)

| Table          | Purpose                                      | Key Design |
|----------------|-----------------------------------------------|------------|
| `events`       | Raw webhook payloads (audit + idempotency)   | `delivery_id` unique, `processed` flag |
| `raw_data`     | Cleaned, searchable content                  | Linked to `events` via `record_id` |
| `entities`     | Canonical nodes (PERSON, SYSTEM, TICKET, etc.)| `id: uuid`, `name`, `type`, `metadata` JSONB |
| `edges`        | Relations (OWNS, FIXES, etc.)                | `source_id`/`target_id` → `entities.id` (grounded) |
| `contributions`| Metrics (in progress)                        | Future normalization to `entity_id` |

### 3. Queueing Layer (Upstash Redis)

- Streams with consumer groups → true exactly-once processing
- `XACK` + `XDEL` only on success
- Automatic group recovery on cold start (`NOGROUP` handling)
- Pub/Sub for real-time Slack responses

### 4. NLP Processor Layer (Python — `nlp/`)

- Deterministic JSON-object prompts (LLM forced to return `{ "entities": [...] }`)
- Grounded relation extraction: entities inserted first → text → UUID mapping → edges inserted
- Safe upserts with individual-insert fallback (`db_helpers.py`)
- Full referential integrity — no dangling edges
- Comprehensive logging, caching, and error recovery

## Current Achievements (Production-Grade)

- Exactly-once ingestion from Slack & GitHub
- Deterministic entity & relation extraction (Groq Llama 3.1 + strict JSON schema)
- UUID-grounded knowledge graph (no text-based edges)
- Resilient consumer with auto-recovery
- Full audit trail and query logging
- Zero hallucinations in structured extraction (enforced schema)

## Data Flow — Current (Working)

1. **Ingestion**

   ```txt
   Webhook → Go → events + raw_data → Redis stream (slack_jobs / github_jobs)
   ```

2. **KG Construction**

   ```txt
   Python consumes stream → NER → insert entities → map name→id → RE → insert edges → mark processed
   ```

3. **Query (v1 — Working, to be replaced)**

   ```txt
   @KMS query → Go → query_jobs → Python → simple ILIKE search → LLM → publish answer → Slack
   ```

## Next Phase: Query Engine v2 (In Progress — 2-Week Sprint)

| Feature                      | Status            | Impact |
|------------------------------|-------------------|--------|
| `pgvector` + embeddings      | Ready to enable   | Semantic search |
| Vector search on `raw_data`  | Implementation    | <100ms recall |
| Multi-hop graph traversal    | Design complete   | “Who owns X?” → real answers |
| Result ranking + citation    | Planned           | Trust & transparency |
| Query caching (Redis)        | Planned           | <50ms cold → <10ms warm |
| Confidence decay & TTL       | Planned           | Stale knowledge auto-expires |

## Scalability & Reliability

- Go backend: Vercel serverless (auto-scale)
- Python worker: Render (free tier → paid on traction)
- Redis: Upstash (10K ops/day → scale on demand)
- Supabase: Free tier → paid at 50+ users
- All components stateless or replayable

## Edge Cases Handled

- Redeliveries → `delivery_id` deduplication
- Redis downtime → consumer auto-reconnect + group recovery
- LLM malformed output → strict parsing + fallback
- Partial failures → no `XACK` → automatic retry
- Large pushes → commit truncation (20 max)

## Roadmap (Next 8 Weeks)

| Milestone                    | ETA         |
|------------------------------|-------------|
| Query Engine v2 (vector + graph) | End Nov 2025 |
| VS Code extension            | Dec 2025    |
| Onboarding playbooks         | Dec 2025    |
| Knowledge health dashboard   | Jan 2026    |
| Jira / Linear integration    | Jan 2026    |
| First 20 beta users          | Jan 2026    |
