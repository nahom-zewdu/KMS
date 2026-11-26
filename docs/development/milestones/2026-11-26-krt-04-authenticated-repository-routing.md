# KRT-04.8 — Authenticated Repository Propagation and Production Routing

**Status:** IMPLEMENTED — PENDING LOCAL VERIFICATION  
**Date:** 2026-11-26  
**Branch:** `feat/krt-04-evidence-gathering`

## Goal

Connect the KRT-04 planned-query pipeline to the production query path without trusting arbitrary repository selectors, silently choosing among repositories, or changing the existing structured/conversation routes.

## Trust boundary

1. `POST /query` authenticates the caller and verifies membership in the requested company.
2. An optional `repository` selector is resolved by the API through `ResolveRepositoryForCompany(company_id, selector)`.
3. Only the resulting canonical repository full name is placed in the dedicated top-level `JobPayload.Repository` field.
4. Worker normalization reads repository scope only from that top-level field. A nested `payload.repository` is retained as ordinary request data and never promoted to trusted scope.
5. `TrustedRepositoryScopeResolver` resolves the canonical full name (or an internal ID for trusted internal callers) with an exact company predicate and requires an active snapshot. If no selector is supplied, it resolves only when exactly one active repository exists.
6. Existing KRT-03 retrievers independently apply company, repository, and active-snapshot predicates.

A repository selector is not itself authorization. API verification and worker-side resolution both remain mandatory.

## Production routing

Supported passage, declaration-discovery, and call-site queries are classified and routed through `PlannedQueryExecutor` before the legacy source-code retrieval path. The planned path uses bounded evidence gathering, grounded synthesis, and citation-membership validation.

- Structured facts remain on the existing authoritative structured handler.
- Courtesy and conversation-control cases remain on their existing early handling.
- Missing or ambiguous repository scope produces an explicit abstention; it does not fall back to company-wide legacy retrieval for supported code-intelligence intents.
- Query types outside the supported KRT-04 intents retain the legacy adaptive route for now.
- Claim-level citations are included in the API response when present.

## Tests added or extended

- Go API security tests: valid company/repository propagation and cross-company repository rejection.
- Worker normalization: top-level repository is preserved; nested payload repository is not promoted.
- Repository resolver: canonical full name resolves to the internal repository ID under company scope.
- QueryEngine integration: supported code query uses the resolved repository and planned executor.
- QueryEngine safety: ambiguous repository inventory abstains without invoking legacy broad retrieval.

## Verification

Pending user execution after pulling the latest branch:

```bash
# NLP
uv run pytest -q tests/test_repository_scope.py tests/test_worker_repository_scope.py tests/test_query_engine_context.py
uv run pytest -q

# Go API
go test ./...
```

Run Go commands from the repository's `api` directory if that is where the Go module is defined.

## Known limitations

- The classifier remains deterministic and lexical; query intent quality needs evaluation.
- Citation validation checks membership in retrieved evidence, not semantic entailment.
- The legacy adaptive retrieval path remains active for unsupported or otherwise unhandled query classes.
- If a company has multiple active repositories and the caller omits a selector, supported code queries abstain. The UI may later expose an explicit repository picker, but that is not part of this milestone.
- RLS/security reconciliation remains a separate release gate and is not changed here.
