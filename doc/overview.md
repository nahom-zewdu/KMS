# KMS System Design Overview

## Introduction

KMS (Knowledge Management System) is an AI-powered knowledge oracle designed for SaaS and fintech teams to reduce onboarding friction and eliminate knowledge silos. It integrates with tools like Slack and GitHub to extract, organize, and query contextual knowledge, providing verifiable answers to questions such as "Who owns the billing service?" or "What PR fixed the incident last week?" The system emphasizes real-time event ingestion, intelligent processing, and a structured knowledge graph, enabling teams to access insights quickly and accurately. Built with a hybrid architecture, KMS prioritizes efficiency, scalability, and reliability within free-tier limits of services like Supabase and Upstash Redis.

The design follows event-driven principles, separating concerns into ingestion, storage, processing, and querying. It handles 100 events/day for 20 beta users, scaling to 1M events/month, with <100ms latency for ingestion and <1s for queries.

## Architecture Overview

KMS uses a microservices-like structure with two main components: a Go backend for event ingestion and a Python processor for NLP analysis. Data flows through queues for async processing, ensuring decoupling and fault tolerance.

- **Frontend Integration**: Slack bot and GitHub webhooks serve as entry points.
- **Backend (Go)**: Handles incoming events, stores raw data, and queues for processing.
- **Storage (Supabase)**: Central database for raw events, summarized content, knowledge graph, and metrics.
- **Queueing (Redis)**: Streams for event queues (slack_jobs, github_jobs, query_jobs) and Pub/Sub for real-time responses (query_results).
- **NLP Processor (Python)**: Consumes queues, extracts knowledge, updates graph/metrics.
- **Deployment**: Backend on Vercel, processor on Render (free tier), with Colab for testing.

Text Diagram:

```txt
Slack/GitHub Webhooks → Go Backend (Ingestion) → Supabase (Storage) + Redis (Queues)
                                             ↓
                                     Python NLP Processor (Extraction) → Supabase (Graph/Metrics)
                                             ↑
Slack Responses ← Redis Pub/Sub (Real-Time)
```

## Key Components

1. **Ingestion Layer (Go Backend)**:
   - Receives webhooks from Slack (`/slack/events`) and GitHub (`/github`).
   - Verifies signatures for security.
   - Stores raw payloads in `events` and summarized content in `raw_data`.
   - Queues events in Redis streams (`slack_jobs`, `github_jobs`, `query_jobs`) for async processing.
   - Design Decision: Hybrid services (SlackIngestService, GitHubIngestService) share core logic for maintainability.

2. **Storage Layer (Supabase)**:
   - **events**: Raw payloads for auditability (delivery_id for idempotency, processed flag).
   - **raw_data**: Summarized content (linked to events for traceability).
   - **entities/edges**: Knowledge graph (entities: PERSON, PROJECT, TICKET; edges: authored, assigned, fixes).
   - **contributions**: Metrics (commit/pr/issue counts, bus factor per person/repo).
   - **pull_requests/issues**: GitHub details (merged status for unmerged PRs, state for issues).
   - Design Decision: Layered schema separates raw/processed data, with indexes for fast queries and RLS for security.

3. **Queueing Layer (Redis)**:
   - Streams for batch processing (e.g., slack_jobs for messages, query_jobs for bot queries).
   - Pub/Sub for real-time responses (query_results: queryID for Slack bot).
   - Design Decision: Event-driven decoupling allows independent scaling of backend and processor.

4. **NLP Processor Layer (Python)**:
   - Consumes streams, extracts entities/relationships using free LLMs.
   - Updates knowledge graph and metrics in Supabase.
   - Generates query answers and publishes responses.
   - Design Decision: Modular files (main, ner, re, query_handler, utils) for maintainability; free models for MVP.

## Data Flow

1. **Ingestion Flow**:
   - Webhook → Backend Handler → Service Validation → CoreIngest (store in events/raw_data, publish to source_jobs).
   - Example: Slack message "Nahom owns billing" → Stored raw, summarized, queued in slack_jobs.

2. **Processing Flow**:
   - Python consumes source_jobs → NER/RE → Update entities/edges/contributions/pull_requests/issues → Set processed: true.
   - Example: GitHub push → Extract PERSON (Nahom), PROJECT (billing), update contributions (commit_count +=1).

3. **Query Flow**:
   - Slack `@KMS who owns billing?` → Backend publishes to query_jobs → Python consumes, searches Supabase, generates answer → Publishes to query_results → Backend posts to Slack.
   - Example: Search entities/raw_data → LLM generates "Nahom owns billing [80% commits]".

4. **Metrics Flow**:
   - GitHub events → Update contributions (e.g., bus factor = max(commit_count)/total_commits).
   - Edge Case: Unmerged PRs counted in pr_count, but flagged merged: false.

### Edge Cases

- **Unmerged PRs/Commits**: Stored in pull_requests/issues with merged/state flags, counted in contributions for metrics (e.g., active devs).

- **Deleted Repos**: Mark entities active: false via repository event.
- **Rate Limits**: Cache queries in Redis (delivery_id checks).
- **Redeliveries**: Skip duplicates using delivery_id in events.
- **Noisy Data**: NER/RE thresholds (>0.5 score) filter low-confidence results.

### Scalability and Efficiency

- **Horizontal Scaling**: Backend on Vercel (auto-scales), processor on Render (free tier).
- **Efficiency**: Batch processing (10 events), LLM quantization (<1s/query).
- **Free Tools**: HuggingFace models, Supabase PGVector, Upstash Redis, Colab for testing.

This design makes KMS efficient and intelligent, ready for growth. Feedback?
