# KMS — AI-Powered Knowledge Oracle

**KMS** passively captures tribal knowledge from Slack and GitHub, builds a real-time knowledge graph, and answers natural-language questions like:

- “Who owns the billing service?”
- “What was the context behind the last payment API change?”
- “Which PR fixed KMS-123?”

By connecting scattered signals across tools, KMS eliminates onboarding friction, reduces repetitive questions, and mitigates bus-factor risk in engineering teams.

## Current Status — MVP (Working End-to-End)

- Slack & GitHub event ingestion (exactly-once)
- Production-grade entity & relation extraction (grounded to UUIDs)
- Real-time Slack bot (`@KMS`) with query → answer loop
- Resilient Redis Streams + consumer groups
- Supabase-backed knowledge graph (`entities`, `edges`, `raw_data`, `events`)
- Full referential integrity (no dangling edges)

## Architecture Overview

```txt
Slack / GitHub Webhook
        ↓
   Go Backend (Gin)
        ↓
   Redis Streams → slack_jobs / github_jobs / query_jobs
        ↓
   Python NLP Worker (RedisStreamConsumer)
        ↓
   NER → Entities → RE → Edges (UUID-grounding)
        ↓
   Supabase (knowledge graph)
        ↓
   Query → Vector/Graph Search → LLM → Answer → Slack Thread
```

## Project Structure

```txt
kms/
├── api/                  # Go backend (webhooks, Slack bot, ingestion)
│   ├── domain/           # Shared interfaces & structs
│   ├── handlers/         # Slack & GitHub webhook endpoints
│   ├── repository/       # Redis & Supabase adapters
│   ├── services/         # Core ingestion + source-specific logic
│   └── main.go
│
├── nlp/                  # Python NLP processor
│   ├── worker/
│   │   ├── consumer.py      # Exactly-once Redis stream consumer
│   │   ├── ingestion.py     # NER + RE + grounded KG build
│   │   ├── query.py         # Query handler (v1 — being replaced)
│   │   └── processor.py
│   ├── engine/
│   │   ├── llm.py           # Groq + JSON-mode interface
│   │   ├── ner.py / re.py   # Deterministic entity & relation extraction
│   │   ├── prompt.py        # Strict JSON-object prompts
│   │   └── schema.py        # Pydantic models
│   ├── utils/
│   │   ├── db_helpers.py    # Safe upsert + fallback logic
│   │   ├── supabase.py
│   │   └── redis.py
│   ├── query_handler.py     # Current query logic (to be upgraded)
│   └── main.py              # Entry point
│
└── README.md
```

## Local Development

### 1. Clone & Setup

```bash
git clone https://github.com/nahom-zewdu/kms.git
cd kms
```

### 2. Environment Variables (`.env` in both `api/` and `nlp/`)

```env
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key

# Redis (Upstash)
REDIS_URL=rediss://:password@host:port

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...

# Groq (for LLM)
GROQ_API_KEY=gsk_...

# Github
GITHUB_WEBHOOK_SECRET=your-github-secret-key
GITHUB_API_TOKEN=ghp_ ...


# Optional
PORT=9090
```

### 3. Run Go Backend

```bash
cd api
go mod tidy
go run main.go
```

### 4. Run Python NLP Worker

```bash
cd nlp
pip install -r requirements.txt
python main.py
```

### 5. Test the Flow

- Send a Slack message: `Nahom owns the billing service`
- Trigger a GitHub push or PR
- Ask in Slack: `@KMS Who owns billing?`

→ Answer appears in thread within seconds.

## Tech Stack

| Layer         | Technology                                   |
|---------------|-----------------------------------------------|
| Backend       | Go (Gin)                                      |
| NLP / LLM     | Python + Groq (Llama 3.1 70B / 8B) + JSON mode |
| Vector Search | Planned: `pgvector` + `sentence-transformers` |
| Database      | Supabase (Postgres)                           |
| Message Queue | Upstash Redis (Streams + Pub/Sub)             |
| Hosting       | Vercel (Go) + Render (Python)                 |

## Key Achievements (Production-Ready)

- Exactly-once processing with consumer groups
- Deterministic LLM prompts (JSON-object schema)
- Grounded relations (`source_id`/`target_id` → real UUIDs)
- Safe upserts with individual-insert fallback
- Full audit trail (`events`, `raw_data`, query logs)

## Upcoming (Next 2–4 Weeks)

| Feature                     | Status     |
|-----------------------------|------------|
| `pgvector` + semantic search| In progress     |
| Multi-hop graph traversal   | Planned         |
| Query result caching        | Planned         |
| Confidence decay & edge TTL | Planned         |
| VS Code extension           | Planned         |
| Onboarding playbooks        | Planned         |
| Knowledge health dashboard  | Planned         |

## Contributing

Contributions are welcome! Please:

- Follow Go formatting (`gofmt`) and PEP 8
- Add tests where possible
- Open an issue first for big changes

## License

MIT
