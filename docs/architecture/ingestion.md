# Ingestion Architecture

## Flow

```text
Slack/GitHub webhook
        |
        v
Go handler
  - verify provider signature
  - resolve company
  - persist ingestion records
  - publish Redis job
        |
        v
Redis Stream + consumer group
        |
        v
Python worker
  - normalize job
  - extract entities/relations
  - persist graph/raw data
  - publish durable codebase-analysis work when applicable
```

## Tenant invariant

A production ingestion job must carry an explicit resolved `company_id`. Unresolved/default tenant mappings are rejected rather than routed into a shared tenant.

## Failure semantics

Processing failure must propagate to the Redis consumer so the message is not acknowledged as successful. Codebase analysis is separated into its own durable stream job rather than a detached daemon thread.

## Current limitations

The current system still has known technical debt around large-push limits, deleted-file reconciliation, and complete schema/migration adoption. These are documented rather than silently presented as solved guarantees.
