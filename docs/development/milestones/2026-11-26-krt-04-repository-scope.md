# KRT-04.7 — Trusted Repository Scope Resolution

**Status:** VERIFIED — user-reported full suite (408 passed), with KRT-04.8 extension pending verification  
**Date:** 2026-11-26  
**Branch:** `feat/krt-04-evidence-gathering`

## Goal

Establish a narrow repository-selection boundary for planned queries without trusting arbitrary request payload fields or guessing when a company has multiple repositories.

## Changes

Added `nlp/query_engine/repository_scope.py` with `TrustedRepositoryScopeResolver` and immutable `RepositoryScopeResolution`.

- Requires a real, non-placeholder company ID supplied by the trusted caller.
- If a repository ID or canonical full name is provided, queries by both company ID and the selected repository field; the selector is not proof of authorization.
- Accepts only a matching repository row with a non-null active snapshot.
- If no repository selector is supplied, checks for exactly one active repository, using a two-row limit to detect ambiguity.
- Returns explicit reasons for no active repository, a repository not belonging to the company, or multiple active repositories.
- Never chooses an arbitrary repository from a multi-repository company.

Added `nlp/tests/test_repository_scope.py` for unique active selection, multiple-repository ambiguity, explicit repository verification, missing/placeholder company scope, empty inventory, and cross-company selector rejection.

## Integration boundary

KRT-04.8 now carries an API-verified canonical repository full name in a dedicated top-level Redis job field. Worker normalization does not promote nested payload repository values. The Python resolver checks the full name against the trusted company ID and active snapshot before returning the internal repository ID. See `2026-11-26-krt-04-authenticated-repository-routing.md`.

## Verification

User-reported local execution after the test-double correction:

```text
uv run pytest -q tests/test_repository_scope.py
8 passed in 1.31s

uv run pytest -q
408 passed, 8 skipped, 6 warnings, 4 subtests passed in 21.72s
```

KRT-04.8 adds further tests and requires a fresh focused + full-suite run.

## Acceptance

- Repository scope is derived from trusted company scope and verified database ownership.
- No active repository and multiple active repositories fail closed.
- Explicit repository selection cannot cross company boundaries.
- Repository selectors are accepted only after authenticated API verification; worker and retriever layers re-check company ownership and active snapshot.
