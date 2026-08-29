# KMS Reality Reconciliation

> Snapshot: `feat/ramp`, 2026-08-30
>
> This document records what is actually present in the repository and live Supabase database. It is not a product specification and does not treat older documentation as authoritative when code or the live database contradicts it.

## Repository structure

KMS backend is a single repository containing two runtime components:

- `api/` — Go/Gin HTTP backend, webhook ingestion, persistence, Redis publication, query enqueueing, and service endpoints.
- `nlp/` — Python worker/API, NLP extraction, knowledge-graph persistence, codebase analysis, baseline synchronization, and related services.

The frontend is a separate repository:

- `kms-frontend/` — Next.js App Router application containing authentication, global/company workspace UI, integrations, playbooks, and frontend API routes.

The active development line for both repositories is `feat/ramp`. The reliability work was developed from that line in `feat/ingestion-reliability-clean`; it is not the product-development baseline until explicitly merged.

## Current product surface

The current frontend README describes:

- Supabase email/password authentication.
- Multiple companies per user with `admin`, `manager`, and `member` roles.
- Global dashboard and company-scoped workspace.
- Company playbooks.
- Slack and GitHub App integrations.
- Company members/settings/navigation.

Ramp functionality exists on the current branch, including API routes for generating/fetching ramp plans and company navigation into the "First 7 Days" experience.

The existing `doc/overview.md` describes the broader KMS thesis as an engineering knowledge system that captures Slack/GitHub knowledge, builds a knowledge graph, and answers questions. Its status claims are historical and should not be assumed current without verification.

## Architecture currently represented by code

```text
Slack / GitHub
      |
      v
  Go API (`api/`)
      |
      +--> Supabase
      |      - events
      |      - raw_data
      |      - domain records
      |
      +--> Redis Streams
             |
             v
       Python worker (`nlp/`)
          |
          +--> NER / relation extraction
          +--> entities / edges
          +--> codebase analysis jobs
          +--> baseline synchronization

Frontend (`kms-frontend`)
      |
      +--> Supabase Auth / company workspace
      +--> backend/NLP API routes
      +--> Ramp experience
```

The important architectural distinction is that codebase analysis is now represented as a durable Redis job rather than a detached daemon thread on the ingestion path. This was implemented on the reliability branch and should be treated as part of the intended ingestion architecture once that branch is merged.

## Live database is the runtime source of truth

The connected Supabase project currently contains 20 public tables. The live schema includes fields that are absent from the repository's `schema/schemas.sql`, including tenant fields and later-added ingestion/vector fields.

Examples verified against the live database:

- `events.company_id`
- `raw_data.company_id`, `raw_data.embedding`, `raw_data.embedding_model`
- `entities.company_id`
- `edges.company_id`, `edges.confidence`, `edges.source_record_id`, `edges.last_seen_at`, `edges.expires_at`
- `repositories.company_id`
- `codebase_files.company_id`, `codebase_files.module_path`, `codebase_files.importance_score`
- `codebase_modules.company_id`
- `ramp_plans`
- extended GitHub integration fields on `company_integrations`

Therefore the old `schema/schemas.sql` is a stale bootstrap snapshot, not a faithful representation of the current production database.

## Schema divergence that must not be "fixed" blindly

`schema/schemas.sql` currently contains a reset/bootstrap script that drops public tables and then performs later `ALTER TABLE` operations. It also grants broad table permissions and declares older table shapes.

The live database is materially ahead of this file. We should **not** edit the schema file merely to make the declarations look current until the live schema has been captured and the migration strategy has been decided.

The eventual target is:

1. Capture the live schema as a canonical baseline.
2. Establish versioned migrations from that baseline.
3. Reconcile application writers/readers against the canonical schema.
4. Only then remove or replace the legacy reset script.

## Tenant model

The current architecture is company-scoped. The live database has `companies`, `company_members`, `company_integrations`, `company_repos`, and company identifiers on knowledge/ingestion tables.

Webhook tenant resolution is expected to produce an explicit company before ingestion. The reliability work rejects unresolved/default tenants rather than mixing data into a shared fallback tenant.

The frontend company workspace also treats `companyId` as a first-class scope.

## Security state requiring deliberate follow-up

Live RLS status was checked directly. RLS is enabled on:

- `companies`
- `company_integrations`
- `company_members`
- `company_repos`
- `entities`
- `playbooks`
- `profiles`
- `ramp_plans`

RLS is currently disabled on several data/ingestion tables, including:

- `events`
- `raw_data`
- `edges`
- `repositories`
- `codebase_files`
- `codebase_modules`
- `pull_requests`
- `issues`
- `query_logs`
- `contributions`
- `file_entity_links`

This is a real security gap, but it should not be repaired by blindly enabling RLS. The access model must first distinguish browser/user access from server-side service-role access and establish membership-based policies.

## Reliability work status

The reliability investigation found and the current reliability branch addressed major failure-semantics problems around tenant resolution, NLP failure propagation, Redis pending-message recovery, and detached codebase analysis.

The following remain known technical debt rather than product work:

- deleted-file lifecycle/reconciliation in codebase indexing
- company-scoped repository uniqueness migration
- large-push orchestration beyond current limits
- canonical schema/migration adoption
- complete RLS policy model

These should not become another open-ended reliability phase. They should be handled when a concrete product feature or deployment requirement makes them necessary, except for security issues that block safe customer access.

## What this reconciliation changes

Going forward, use these sources in this order when they conflict:

1. Current code on the active feature branch.
2. Live Supabase schema/data behavior.
3. Tests and executable behavior.
4. Repository documentation.
5. Older planning documents and historical claims.

Older claims such as "exactly-once" or "production-grade" must be treated as assertions to verify, not facts to inherit.

## Immediate development direction

This reconciliation is deliberately stopping here. We are not spending another sprint polishing infrastructure before customers can use the product.

The next stage is customer-facing development and validation of the core KMS value proposition, with Ramp as the current product surface. Reliability/security/schema debt should be addressed opportunistically when it blocks a real user flow or creates unacceptable risk.
