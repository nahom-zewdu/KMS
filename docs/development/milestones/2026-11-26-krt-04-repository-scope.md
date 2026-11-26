# KRT-04.7 — Trusted Repository Scope Resolution

**Status:** IMPLEMENTED — PENDING LOCAL VERIFICATION  
**Date:** 2026-11-26  
**Branch:** `feat/krt-04-evidence-gathering`

## Goal

Establish a narrow repository-selection boundary for planned queries without trusting arbitrary request payload fields or guessing when a company has multiple repositories.

## Changes

Added `nlp/query_engine/repository_scope.py` with `TrustedRepositoryScopeResolver` and immutable `RepositoryScopeResolution`.

- Requires a real, non-placeholder company ID supplied by the trusted caller.
- If a repository ID is provided, queries by both company ID and repository ID; the ID is treated as a selector, not proof of authorization.
- Accepts only a matching repository row with a non-null active snapshot.
- If no repository selector is supplied, checks for exactly one active repository, using a two-row limit to detect ambiguity.
- Returns explicit reasons for no active repository, a repository not belonging to the company, or multiple active repositories.
- Never chooses an arbitrary repository from a multi-repository company.

Added `nlp/tests/test_repository_scope.py` for unique active selection, multiple-repository ambiguity, explicit repository verification, missing/placeholder company scope, empty inventory, and cross-company selector rejection.

## Integration boundary

This resolver is not yet wired into `QueryEngine.handle_query`. The current Redis job has a trusted company ID but does not carry an independently authenticated repository selector. A future caller may supply a selector only when it originates from server-side authorized context; a repository ID in arbitrary question payload data must not be trusted.

The existing structured-fact, conversation, source-code, adaptive retrieval, cache, analytics, and Redis publication routes remain unchanged.

## Verification

Pending local execution:

```bash
uv run pytest -q tests/test_repository_scope.py
uv run pytest -q
```

## Acceptance

- Repository scope is derived from trusted company scope and verified database ownership.
- No active repository and multiple active repositories fail closed.
- Explicit repository selection cannot cross company boundaries.
- Existing QueryEngine behavior remains unchanged until an authenticated repository-selection contract is available.
