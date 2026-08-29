# Local Development Setup

## Backend API

Requirements: Go 1.21+ and environment variables for Supabase, Redis, Slack, and GitHub integration as applicable.

```bash
cd api
go run main.go
```

The API listens on the configured `PORT` (README default: `9090`).

## NLP worker

Requirements: Python 3.11+ and `uv` recommended.

```bash
cd nlp
uv run main.py
```

## NLP HTTP service

```bash
cd nlp
uv run api.py
```

The README currently documents port `8000` for the FastAPI service.

## External services

A useful local environment requires access to the configured Supabase project and Redis instance. Slack and GitHub credentials are needed when exercising real webhook/integration flows; LLM-backed extraction requires the configured Groq credential.

Never commit secrets or place service-role credentials in frontend/browser code.

## Frontend

The Next.js frontend lives in the separate `kms-frontend` repository. Its local setup and environment variables should be documented there so the backend repository does not become a second source of truth.
