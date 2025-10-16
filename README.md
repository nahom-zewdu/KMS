# KnowSphere (KMS) - AI-Powered Knowledge Oracle

KnowSphere is an AI-powered knowledge oracle for SaaS/fintech teams, integrating with Slack and GitHub to eliminate onboarding friction and knowledge silos. It extracts entities (PERSON, PROJECT, TICKET) and relationships from messages/events, building a verifiable knowledge graph in Supabase for instant answers like "Who owns the billing service?" or "What PR fixed the incident last week?"

## MVP Scope

- **Slackbot**: Ingests messages, handles `@KMS` queries via `query_jobs`, responds with LLM-generated answers using Supabase context.
- **GitHub Integration**: Processes webhooks (`push`, `pull_request`, `issues`), stores raw payloads in `events`, summarized content in `raw_data`, publishes to `github_jobs`.
- **Knowledge Graph**: Entities/edges for relationships (authored, assigned, fixes), metrics (contributions, bus factor).
- **Architecture**: Hybrid with source-specific services (`SlackIngestService`, `GitHubIngestService`) and shared `CoreIngestService`.
- **Performance**: <100ms latency, 1K QPS, 99.9% uptime within free-tier limits (Upstash 10K ops/day, Supabase 500MB, GitHub API 5K/hour).

## Project Structure

```text
kms/
├── api/
│   ├── domain/
│   │   ├── domain.go      # Shared structs/interfaces (IngestRequest, CoreIngestService)
│   │   ├── slack.go       # Slack-specific structs/interfaces
│   │   └── github.go      # GitHub-specific structs/interfaces
│   ├── handlers/
│   │   ├── slack.go       # Slack webhook handler
│   │   ├── github.go      # GitHub webhook handler
│   │   └── routes.go      # Route configuration
│   ├── repository/
│   │   ├── redis_stream.go # Redis operations
│   │   └── supabase.go     # Supabase operations
│   ├── services/
│   │   ├── core.go        # Shared ingestion logic
│   │   ├── slack.go       # Slack ingestion
│   │   ├── slack_bot.go   # Slack bot query handling
│   │   └── github.go      # GitHub ingestion
│   └── main.go            # Entry point
├── nlp/
│   └── hf_processor.py    # Python worker for event processing/query answering
├── .env                   # Environment variables
└── README.md              # This file
```

## How to Run Locally

1. Clone the repo:

   ```bash
   git clone https://github.com/nahom-zewdu/kms.git
   cd kms
   ```

2. Set up `.env`:

   ```env
   SUPABASE_URL=https://your-supabase-project.supabase.co
   SUPABASE_KEY=your-service-key
   REDIS_ADDR=sought-perch-5675.upstash.io:6379
   REDIS_PASSWORD=your-redis-password
   SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
   SLACK_SIGNING_SECRET=your-slack-signing-secret
   GITHUB_WEBHOOK_SECRET=your-github-secret
   HF_API_TOKEN=your-huggingface-token
   PORT=9090
   ```

3. Install Go dependencies:

   ```bash
   cd api
   go mod tidy
   ```

4. Run Go backend:

   ```bash
   go run main.go
   ```

5. Install Python dependencies:

   ```bash
   cd nlp
   pip install -r requirements.txt  # Create requirements.txt with: redis langchain-huggingface supabase python-dotenv retry transformers torch
   ```

6. Run Python processor:

   ```bash
   python hf_processor.py
   ```

7. Test:

- **Slack Message**: Send "Nahom owns billing" → Stored in Supabase, published to `slack_jobs`.
- **@KMS Query**: Send "@KMS Who owns billing?" → Processed via `query_jobs`, response posted in thread.
- **GitHub Push**: Trigger a push → Stored in Supabase, published to `github_jobs`.

## Tech Stack

- **Go (Gin)**: Backend for webhook handling and Slack bot.
- **Python (HuggingFace)**: LLM/NER processing (`distilgpt2`, `distilbert-base-cased`).
- **Supabase**: Knowledge graph storage (`events`, `raw_data`, `entities`, `edges`).
- **Upstash Redis**: Streams (`slack_jobs`, `github_jobs`, `query_jobs`), Pub/Sub (`query_results:{query_id}`).

## Key Features

- **Event Ingestion**: GitHub webhooks and Slack messages stored as raw payloads for auditability.
- **Knowledge Graph**: Entities/relationships extracted from events, supporting metrics like bus factor.
- **Query Handling**: Real-time answers via Slack bot, with LLM context from Supabase.
- **Metrics**: Contribution tracking (commits/PRs/issues) and bus factor calculation.

## Upcoming Features

- **Jira Integration**: Link tickets to GitHub events.
- **NLP Enhancements**: Fine-tuned models for 85%+ accuracy.
- **Deployment**: Vercel (Go) and Heroku/Render (Python).

## Contributing

Contributions welcome! Submit PRs with clean code (gofmt, PEP 8) and tests.

## License

MIT License
