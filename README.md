# KMS — AI-Powered Knowledge Oracle

**KMS** passively captures tribal knowledge from Slack and GitHub, builds a real-time knowledge graph, and answers natural-language questions like:

- “Who owns the billing service?”
- “What was the context behind the last payment API change?”
- “Which PR fixed KMS-123?”

By connecting scattered signals across tools, KMS eliminates onboarding friction, reduces repetitive questions, and mitigates bus-factor risk in engineering teams.

## Current Status MVP (Working End-to-End)

- Slack & GitHub event ingestion (exactly-once)
- Production-grade entity & relation extraction (grounded to UUIDs)
- Real-time Slack bot (`@KMS`) with query → answer loop
- Resilient Redis Streams + consumer groups
- Supabase-backed knowledge graph (`entities`, `edges`, `raw_data`, `events`)
- Full referential integrity (no dangling edges)
- Full multitanent and RBAC support

This repository contains:

- **`api/`** — Go (Gin) webhook ingress, signature verification, Redis job publish, query bridge
- **`nlp/`** — Python worker (NER/RE, query engine, playbooks, codebase baseline/visualizer) + FastAPI helpers

## Architecture

```text
Slack / GitHub webhooks
        │
        ▼
   api/ (Go :9090)
   - verify signatures
   - resolve company_id (Slack team_id / GitHub installation)
   - write events + raw_data (as applicable)
   - publish Redis streams (slack_jobs | github_jobs | query_jobs | codebase_baseline_jobs)
        │
        ▼
   nlp/main.py (consumer group: kms)
   - NER → RE → entities/edges
   - embeddings on raw_data
   - query_engine → Pub/Sub query_results:{id}
   - codebase analyzer / baseline sync

   nlp/api.py (FastAPI :8000)
   - POST /playbooks/generate
   - GET  /visualizer
   - GET  /github/sync-baseline
```

## Multi-tenancy

| Source | Resolution |
|--------|------------|
| Slack | `team_id` → `company_integrations` (`provider=slack`) |
| GitHub | `installation.id` (preferred) or owner login → `company_integrations` (`provider=github`) |

`company_id` is propagated on Redis job payloads and stored on knowledge data (`raw_data`, `entities`, `edges`, repositories, etc.). Query, playbook, and visualizer paths filter by `company_id`.

## Prerequisites

- Go 1.21+
- Python 3.11+ (uv recommended)
- Supabase (Postgres + service role key)
- Upstash Redis (TLS)
- Slack app (Events API + bot)
- GitHub **App** (webhooks + install flow; private key for JWT)
- Groq API key (LLM)
- Optional: `GITHUB_API_TOKEN` for baseline tree walk via PyGithub

## Environment

### `api/`

```bash
SUPABASE_URL=
SUPABASE_KEY=
REDIS_ADDR=
REDIS_PASSWORD=
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
GITHUB_WEBHOOK_SECRET=
PORT=9090
```

### `nlp/`

```bash
SUPABASE_URL=
SUPABASE_KEY=
REDIS_URL=          # rediss://...
GROQ_API_KEY=
GITHUB_API_TOKEN=   # baseline sync (temporary)
```

Frontend owns GitHub App OAuth/install env (`GITHUB_APP_ID`, `GITHUB_APP_SLUG`, private key, etc.).

## Run

```bash
# Go API
cd api && go run main.go

# NLP worker
cd nlp && uv run main.py

# Playbook / visualizer / baseline HTTP
cd nlp && uv run api.py
```

Public webhook URLs (e.g. ngrok) must point:

- Slack + GitHub **App webhook** → Go `/slack/events`, `/github/`
- GitHub App **callback** → frontend `/api/integrations/github/callback`

## Main endpoints (Go)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/slack/events` | Slack Events API |
| POST | `/github` | GitHub App / webhook events |
| POST | `/query` | Enqueue query job |
| GET | `/github/sync-baseline?repo=` | Queue baseline (prefer company-aware callers) |
| GET | `/health` | Health check |

## Main endpoints (Python FastAPI)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/playbooks/generate` | Body: `role`, `employee_name`, `company_id` |
| GET | `/visualizer?role=&company_id=` | Onboarding structure data |
| GET | `/github/sync-baseline?repo=&company_id=` | Full repo index for a company |

## Project layout

```text
api/
  domain/ handlers/ services/ repository/
nlp/
  worker/          # consumer, ingestion, query, baseline
  query_engine/
  engine/          # NER, RE, LLM
  codebase/        # analyzer, baseline
  playbooks/
  visualizer/
  utils/
```

## License

MIT
