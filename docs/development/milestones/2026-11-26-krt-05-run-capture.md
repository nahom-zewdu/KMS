# KRT-05.4 — Opt-in sanitized LLM run capture

**Status:** IMPLEMENTED — pending local verification  
**Branch:** `feat/krt-05-evaluation`

## Purpose

Capture reproducibility and operational metadata for local evaluation without retaining prompts, model responses, source code, or secrets.

## Behavior

Set `KMS_LLM_RUN_CAPTURE_PATH` to an explicit local JSONL file path to enable capture. When unset, capture is disabled. Each record contains schema version, timestamp, model, temperature, output-token limit, duration, status, SHA-256 hashes of prompt/output, and provider token counts only when supplied.

The file is created with restrictive owner-only permissions (0600) and appended to. Parent directories must already exist. No raw prompt/output content is persisted. Capture is local and opt-in; this is not production telemetry.

## Limitations

- Existing cached LLM results do not produce provider-run records because no provider request occurs.
- Token usage is recorded only when the provider response exposes usage metadata.
- Hashes support equality/reproducibility checks, not reconstruction.
- Operators must protect and manage the configured local artifact file.
