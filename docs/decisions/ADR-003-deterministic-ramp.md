# ADR-003: Deterministic Ramp Generation

## Status
Accepted

## Context

An onboarding plan must be useful because it reflects the customer's actual codebase and knowledge, not because an LLM invents a plausible checklist.

## Decision

Ramp plan structure is generated deterministically from company-scoped visualizer, codebase, and ownership signals. An LLM may polish explanatory text, but it must not invent people, files, or ownership facts.

Ramp step IDs are deterministic/stable so a step can be referenced by the UI.

## Consequences

The same underlying company signals produce a predictable structure and make evidence traceability possible. Changes in source data can intentionally change the plan rather than producing arbitrary LLM output.

## Product constraint

Determinism is a means to trustworthiness, not the product itself. Customer validation must determine whether the resulting onboarding experience actually saves time.
