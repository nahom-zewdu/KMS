# Architecture Overview

> Current-state snapshot: `feat/ramp`, 2026-08-30. This document describes the system as it exists, not an aspirational architecture.

## System boundary

KMS spans two repositories plus managed infrastructure:

- **`KMS`** — Go API under `api/` and Python worker/services under `nlp/`.
- **`kms-frontend`** — separate Next.js App Router application.
- **Supabase/Postgres** — persistent application and knowledge data.
- **Redis Streams** — asynchronous work transport.
- External providers: Slack and GitHub.

```text
Slack / GitHub
      |
      v
Go API (`KMS/api`)
   |              |
   v              v
Supabase      Redis Streams
                 |
                 v
          Python (`KMS/nlp`)
          |      |       |
          v      v       v
         NER    RE   codebase analysis
          |      |
          +----> knowledge graph

Next.js (`kms-frontend`)
   |
   +--> Supabase Auth / company workspace
   +--> authenticated Next.js API routes
   +--> NLP/Go service endpoints
   +--> Ramp workspace
```

## Runtime responsibilities

### Go API

Owns HTTP ingress, Slack/GitHub webhook verification, company resolution, event persistence/publication, Redis job publication, and the synchronous query bridge.

### Python NLP

Owns Redis consumption, NER/relation extraction, knowledge-graph writes, embeddings/query processing, codebase analysis, baseline synchronization, playbook generation, visualizer data, and Ramp generation/fetching.

The current `feat/ramp` branch includes the durable codebase-analysis stream design: GitHub push ingestion publishes a `codebase_analysis_jobs` job, and `processor.py` registers a dedicated handler. This is part of the current branch rather than merely a planned design.

### Frontend

Owns authentication/session UX, global and company workspaces, company membership/settings, Slack/GitHub connection UX, playbooks, and the Ramp experience.

## Current customer-facing loop

The strongest implemented product surface is **First 7 Days / Ramp**:

1. A user enters a company workspace.
2. An admin/manager can generate a role-specific Ramp plan.
3. The NLP service derives the plan from company-scoped codebase/ownership signals.
4. The plan is persisted in `ramp_plans`.
5. Engineers can open a role-specific workspace and follow the generated steps.

The broader KMS knowledge-query capability also exists in the backend architecture, but the immediate product-development focus is validating whether the Ramp workflow creates enough value to drive adoption.

## Current state versus intended state

Some reliability/security/schema work has already landed on `feat/ramp`; some earlier reports describe branches that no longer exist separately. The branch itself is authoritative for what is currently implemented.

Do not assume these properties merely because older README text claims them:

- exactly-once ingestion;
- production-grade extraction;
- complete tenant isolation;
- complete RLS coverage;
- complete codebase synchronization.

These are engineering/product claims that require executable or live-system evidence.

## Architectural principle

KMS should remain small while customer value is being validated. New infrastructure must solve a demonstrated problem. Correctness and security issues that directly affect customer data or a core user flow are exceptions and should be fixed when encountered.
