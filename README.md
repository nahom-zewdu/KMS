# KMS (Knowledge Management System)

KMS is an AI-powered knowledge oracle for SaaS/fintech teams. It integrates with tools like Slack, GitHub, and Jira to eliminate onboarding friction and knowledge silos. KMS extracts and organizes contextual knowledge to instantly answer developer questions such as:

> "Who owns the billing service?"  
> "What PR fixed the incident last week?"

## 🧠 MVP Scope

This repository currently implements the **Slack ingestion** feature:

- A `/ingest` endpoint to receive Slack event webhooks  
- Stores raw events in Supabase  
- Publishes ingestion events asynchronously to Redis Streams (Upstash REST API) for downstream processing  
- Built with clean architecture principles (handlers → service → repository → storage/publisher ports)

## 📁 Project Structure

``` txt
kms/
├── api/
│   ├── domain/            # Core business models and interfaces
│   ├── handlers/          # HTTP handlers (e.g. /ingest)
│   ├── repository/        # Implementation of storage interfaces (Supabase, Redis publisher)
│   ├── services/          # Business logic layer (SlackService)
│   └── main.go            # Application entrypoint
```

## 🧪 How to Run Locally

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/kms.git
cd kms
```

### 2. Setup environment variables

Create a `.env` file:

```env
SUPABASE_URL=your-supabase-project-url
SUPABASE_KEY=your-service-role-key
REDIS_UPSTASH_URL=your-upstash-rest-url
REDIS_UPSTASH_TOKEN=your-upstash-rest-token
PORT=8080
```

### 3. Start the server

```bash
go run api/main.go
```

### 4. Test the ingestion endpoint

```bash
curl -X POST http://localhost:8080/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "slack", "content": "hello world"}'
```

## 📦 Tech Stack

- **Go (Gin)** — Web framework
- **Supabase** — Storage backend
- **Redis Streams (Upstash REST API)** — Asynchronous job queue for ingestion events
- **Clean Architecture** — Maintainable project structure

## 🔜 Upcoming Features

- Slack event signature verification for security
- Async consumer to process Redis stream events
- Retry and backpressure handling for Redis publishing
- GitHub/Jira ingestion modules
- AI/NLP pipeline (spaCy, Pinecone)
- Slackbot MVP with contextual Q\&A

## 🤝 Contributing

Right now, the project is maintained solo. Open to ideas, suggestions, and PRs — just keep it clean, modular, and production-oriented.
