# AI Development Workflow

## Roles

- **Human:** owns product decisions, priorities, customer truth, and final approval.
- **ChatGPT:** architecture partner, investigator, reviewer, and task-spec author.
- **Coding agents (Copilot/Cursor/Claude when available):** inspect the repository, implement bounded tasks, run tests, and report the diff.
- **GitHub:** source of code truth and review history.
- **Documentation:** durable engineering context.
- **Supabase:** runtime database/schema truth.

## Agent task pattern

Give coding agents small batches rather than a giant multi-area assignment. Each task should state scope, invariants, files/areas to inspect, expected behavior, tests, and explicit non-goals.

The agent should inspect before modifying, implement only the requested scope, run focused tests, and report concrete changes and remaining issues.

## Review loop

```text
Product decision
 -> architecture/task specification
 -> coding agent
 -> implementation + tests
 -> diff review
 -> merge
 -> documentation update
```

## Context rule

Do not rely on conversational memory as the project's architecture. If an important decision is durable, record it in `docs/` or an ADR.

## Anti-patterns

- Asking an agent to redesign the whole repository at once.
- Treating an agent's completion report as proof that the implementation is correct.
- Letting old documentation override current code/runtime behavior.
- Continuing infrastructure optimization when the customer-facing product has not been validated.
