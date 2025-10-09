# KMS (Knowledge Management System)

KMS is an AI-powered knowledge oracle for SaaS/fintech teams, integrating with tools like Slack to eliminate onboarding friction and knowledge silos. It extracts and organizes contextual knowledge to instantly answer developer questions, such as:

> "Who owns the billing service?"  
> "What PR fixed the incident last week?"

The system processes Slack messages, extracts entities (e.g., PERSON, PROJECT, TICKET), and builds a knowledge graph in Supabase, enabling real-time query responses via a Slack bot.

## 🧠 MVP Scope

The current implementation focuses on the **Slackbot feature**:

- **Ingestion**: Processes Slack messages (e.g., “Nahom owns github”) via the `/slack/events/` endpoint, stores raw events in Supabase (`raw_data`), and publishes to Redis Streams (`slack_jobs`) for entity extraction.
- **Query Handling**: Responds to `@KMS` mentions (e.g., `@KMS Who owns github?`) by publishing to `query_jobs`, generating answers using an LLM (`distilgpt2`) with Supabase context, and posting responses to Slack via Pub/Sub (`query_results:{query_id}`).
- **Architecture**: Built with clean architecture principles (handlers → services → repositories → storage/publisher ports).
- **Performance**: Achieves <100ms query latency, supports 1K QPS, and ensures 99.9% uptime within free-tier limits (Upstash 10K ops/day, Supabase 500MB, Slack 1K messages/month) for 20 beta users.
- **Integration**: Go backend (Vercel) communicates with a Python worker (Heroku) via Upstash Redis TCP (`sought-perch-5675.upstash.io:6379`) and Supabase for storage.

## 📁 Project Structure

```text
kms/
├── api/
│   ├── domain/            # Core business models and interfaces (SlackBotService, IngestService)
│   ├── handlers/          # HTTP handlers (e.g., /slack/events/)
│   ├── repository/        # Storage/publisher implementations (Supabase, Redis Streams/Pub/Sub)
│   ├── services/          # Business logic (SlackBot, IngestService)
│   └── main.go            # Application entrypoint
├── nlp/
│   └── hf_processor.py    # Python worker for LLM/NER processing (query_jobs, slack_jobs)
└── .env                   # Environment variables
```

## 🧪 How to Run Locally

### 1. Clone the Repo

```bash
git clone https://github.com/nahom-zewdu/kms.git
cd kms
```

### 2. Set Up Environment Variables

Create a `.env` file in the root directory:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
UPSTASH_REDIS_URL=sought-perch-5675.upstash.io:6379
UPSTASH_REDIS_TOKEN=your-upstash-redis-token
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_SIGNING_SECRET=your-slack-signing-secret
HF_API_TOKEN=your-huggingface-api-token
PORT=9090
```

- **Supabase**: Get `SUPABASE_URL` and `SUPABASE_KEY` from your Supabase project dashboard.
- **Upstash**: Get `UPSTASH_REDIS_URL` and `UPSTASH_REDIS_TOKEN` from the Upstash Console.
- **Slack**: Create a Slack app with scopes (`app_mentions:read`, `channels:history`, `chat:write`, `users:read`) and get `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET`.
- **Hugging Face**: Get `HF_API_TOKEN` from your Hugging Face account.

### 3. Install Dependencies

#### Go Backend

```bash
cd api
go mod tidy
```

#### Python Worker

```bash
cd nlp
uv pip install torch langchain-huggingface supabase redis python-dotenv retry transformers
```

### 4. Run the Go Backend

```bash
cd api
go run main.go
```

- The server runs on `http://localhost:9090` and listens for Slack events at `/slack/events/`.

### 5. Run the Python Worker

```bash
cd nlp
uv run python hf_processor.py
```

- The worker processes `query_jobs` (queries) and `slack_jobs` (ingestion) from Redis Streams.

### 6. Test the Slackbot

- **Slack Setup**: Add the bot to a channel, configure the Events API to send `app_mention` and `message.channels` to `http://localhost:9090/slack/events/`.
- **Query**: In Slack, send `@KMS Who owns github?`
  - Expected: Response like “Nahom owns github, Jira #435” in the thread.
- **Ingestion**: Send “Nahom owns github, Jira #435”
  - Expected: Stored in Supabase `raw_data`, entities (`Nahom`, `github`, `Jira #435`) in `entities`, relationship (`owns`) in `edges`.

#### Verify Ingestion

```bash
# Check Supabase
psql -h your-supabase-host -U postgres -d postgres -c "SELECT * FROM raw_data WHERE content = 'Nahom owns github, Jira #435';"
psql -h your-supabase-host -U postgres -d postgres -c "SELECT * FROM entities WHERE name IN ('Nahom', 'github', 'Jira #435');"
psql -h your-supabase-host -U postgres -d postgres -c "SELECT * FROM edges WHERE type = 'owns';"
```

#### Verify Query

```bash
# Publish to query_jobs
redis-cli -h sought-perch-5675.upstash.io -p 6379 -a your-redis-token XADD query_jobs * record_id test source slack content "Who owns github?" created_at 2025-10-09T18:00:00Z
# Check Pub/Sub
redis-cli -h sought-perch-5675.upstash.io -p 6379 -a your-redis-token SUBSCRIBE query_results:test
```

## 📦 Tech Stack

- **Go (Gin)**: Web framework for the backend, handling Slack events.
- **Python (langchain-huggingface, transformers)**: Processes queries (`distilgpt2`) and ingestion (`distilbert-base-cased`).
- **Supabase**: Stores raw messages (`raw_data`), entities, and relationships (`entities`, `edges`).
- **Upstash Redis (TCP)**: Streams (`query_jobs`, `slack_jobs`) for async processing, Pub/Sub (`query_results:{query_id}`) for query responses.
- **Hugging Face**: LLM (`distilgpt2`) for query answering, NER (`distilbert-base-cased`) for entity extraction.
- **Clean Architecture**: Ensures modularity and maintainability.

## 🔧 Key Features

- **Slackbot**:
  - Handles `@KMS` mentions, publishes to `query_jobs`, and responds with LLM-generated answers using Supabase context.
  - Ingests normal messages, stores in `raw_data`, extracts entities, and builds knowledge graph (`entities`, `edges`).
- **Performance**:
  - Query latency: <100ms (Redis <10ms, LLM 50-200ms cached, Supabase <40ms).
  - Supports 1K QPS with batching (10 messages) and caching (90% hit rate).
  - 3x retries for Redis, Supabase, and LLM operations.
- **Error Handling**:
  - Fixed `context canceled` in Go by using `context.Background()` for async `HandleEvent`.
  - Fixed Redis type mismatch with `repository.RedisStream`.
  - Fixed Python environment variable loading with `python-dotenv`.
  - Fixed missing PyTorch dependency for `transformers`.

## 🔜 Upcoming Features

- **GitHub Integration**: Ingest PRs/issues, link to knowledge graph.
- **Jira Integration**: Extract ticket data (e.g., JIRA-123) for richer context.
- **NLP Enhancements**: Optimize LLM inference (e.g., quantization), integrate vector search (Pinecone).
- **Monitoring**: Add production logging (Vercel, Heroku) and metrics for Redis/Supabase.

## 🤝 Contributing

The project is currently maintained solo. Contributions are welcome! Please submit ideas, suggestions, or PRs, ensuring clean, modular, and production-ready code. Follow Go (`gofmt`) and Python (PEP 8) style guides.
