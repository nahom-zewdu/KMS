# KMS Agent Guidance

## Repository structure

KMS backend is one repository with two runtime components:

- `api/`: Go/Gin HTTP ingress, webhook verification, tenant resolution, persistence, Redis publication, and query bridge.
- `nlp/`: Python worker/API, NLP extraction, knowledge graph persistence, query engine, codebase analysis, baseline synchronization, playbooks, and visualizer.

The frontend is a separate repository: `kms-frontend`.

## Source of truth

When documentation and implementation disagree, inspect the current branch and executable behavior first. Treat the live Supabase schema as authoritative for deployed data behavior. Treat older design documents as historical unless verified.

Do not infer that a claimed guarantee such as exactly-once, production-ready, or real-time is true merely because an older document says so.

## Development rules

- Preserve company/tenant scoping throughout ingestion, storage, retrieval, and product flows.
- Do not introduce a shared/default tenant as a fallback for production data.
- Keep Go ingress concerns separate from Python NLP/analysis concerns.
- Reuse the existing Redis stream infrastructure before introducing another queue/orchestration system.
- Prefer small, testable changes over broad rewrites.
- Add or update focused tests for behavior changes.
- Do not modify the database schema spec merely to make stale documentation look correct. Verify the live schema and migration strategy first.
- Do not expand reliability work unless it blocks a customer-facing flow or creates unacceptable security/data risk.

## Product context

KMS is being developed to solve the engineering knowledge/context problem: important organizational and codebase knowledge is fragmented across tools and people. The current product surface includes company workspaces, integrations, knowledge ingestion, and the Ramp onboarding experience.

Product hypotheses are not requirements until validated with real users.

## Working branches

`feat/ramp` is the current product-development baseline. Documentation/reconciliation branches should start from the current `feat/ramp` commit and should not silently pull in unrelated implementation work.
