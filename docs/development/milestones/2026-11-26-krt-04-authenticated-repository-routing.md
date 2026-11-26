# KRT-04.8 — Authenticated Repository Propagation and Production Routing

**Status:** VERIFIED — user-reported local tests  
**Date:** 2026-11-26  
**Branch:** `feat/krt-04-evidence-gathering`

## Goal

Connect the KRT-04 planned-query pipeline to the production query path without trusting arbitrary repository selectors, silently choosing among repositories, or changing existing structured-fact and conversation-control routes.

## Trust boundary

1. The authenticated `POST /query` endpoint verifies membership in the requested company.
2. An optional `repository` selector is resolved through the API storage boundary using that authenticated company ID.
3. Only the canonical repository full name returned by that company-scoped lookup is placed in the dedicated top-level Redis job field.
4. Worker normalization reads trusted repository scope only from that top-level field; nested payload repository values are not promoted.
5. The Python `TrustedRepositoryScopeResolver` resolves the canonical name to the internal repository ID with an exact company predicate and requires an active snapshot. Without a selector, it accepts only one active repository.
6. Existing KRT-03 retrievers continue to enforce company, repository, and active-snapshot scope.

A repository selector is not authorization by itself. API verification and worker-side resolution both remain in place.

## Production routing

Supported passage-retrieval, declaration-discovery, and call-site-navigation queries are routed through `PlannedQueryExecutor` before legacy source retrieval.

- Structured facts remain on the existing authoritative structured handler.
- Courtesy and conversation-control cases remain on existing early handling.
- Missing or ambiguous repository scope produces an explicit abstention instead of falling back to company-wide legacy retrieval for supported code-intelligence intents.
- Query classes outside the supported KRT-04 intents retain the legacy adaptive route.
- Claim-level citations are propagated through the Go API response.

## Verification reported by the developer

Focused tests:

```text
20 passed, 1 warning in 0.97s
```

Full NLP suite:

```text
413 passed, 8 skipped, 6 warnings, 4 subtests passed in 12.32s
```

Go API:

```text
go test ./... — passed across all packages
```

Warnings are existing python-json-logger and PyGithub deprecations.

## Tests added or extended

- API company/repository authorization and verified repository propagation.
- Worker normalization: top-level repository preserved; nested payload repository not promoted.
- Full-name-to-internal-ID resolution under company scope.
- QueryEngine planned routing with trusted repository scope.
- Ambiguous repository inventory abstains without invoking broad legacy retrieval.
- Legacy query behavior remains covered.

## Known limitations

- Citation validation checks membership in the retrieved evidence set, not semantic entailment.
- Intent classification remains a deterministic lexical baseline and needs representative evaluation.
- The legacy adaptive retrieval path remains active for unsupported/unhandled query classes.
- RLS/security reconciliation remains a separate release gate and is not changed here.
