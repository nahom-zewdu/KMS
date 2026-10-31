# Backend Hardening Test Matrix

## Batch 0 status

This batch is focused on architecture verification and documentation. No production security code was changed.

## Validation attempts performed

| Check | Command | Result |
|---|---|---|
| Go module validation | `cd /home/nahom/Projects/personal/KMS && go test ./...` | Failed: root directory is not a Go module. |
| Python test suite validation | `cd /home/nahom/Projects/personal/KMS/nlp && uv run pytest -q tests` | Failed during collection due missing dependencies and package-import setup. |
| Architecture review | static inspection of Go + Python route and tenant code | Completed; findings documented in `PROGRESS.md` and `ARCHITECTURE.md`. |

## Actual observed issues

- The repo root does not contain a Go module; therefore `go test ./...` cannot be used at the repository root.
- The Python test suite is not currently runnable in the checked-out environment because dependencies and import paths are not aligned with the project’s execution assumptions.
- `nlp/api.py` currently contains default `company_id="default"` values on public endpoints, which is a known tenant-scoping risk.

## Test plan for next batches

| Batch | Recommended checks |
|---|---|
| Batch 1 | Cross-tenant access tests, invalid membership tests, policy validation tests |
| Batch 2 | Unauthenticated and unauthorized request tests, role-based authorization tests |
| Batch 3 | Tampered OAuth state, expired state, replay protection, callback validation tests |
| Batch 4 | Request size, bad signature, rate-limit, unauthorized request tests |
| Batch 5 | Graceful shutdown, timeout, panic recovery, request ID/logging tests |
| Batch 6 | Retry, dead-letter, replay, and duplicate-message recovery tests |
| Batch 7 | Structured logs, tracing correlation, metrics smoke tests |
| Batch 8 | Migration idempotency and database lifecycle checks |
| Batch 9 | Tenant-scoped retrieval and vector-search isolation tests |
| Batch 10 | CI smoke, load, and backup/restore validation |

## Acceptance criteria for future batches

A batch is only considered complete when:

- the implementation matches the stated objective,
- the relevant tests exist,
- the tests are actually run,
- results are recorded, and
- the implementation is compatible with the project’s tenant-isolation guarantees.
