# Integrations Architecture

## Slack

Slack Events API delivers events to the Go webhook endpoint. The backend verifies the request, resolves the Slack team to a company integration, persists the event/data required by the ingestion path, and publishes asynchronous work.

Slack also provides the current conversational/query interface through the KMS bot workflow.

## GitHub

KMS uses a GitHub App for repository/event integration. Installation identity is the preferred tenant-resolution signal. The frontend contains the GitHub App install/callback/repository selection experience; the backend handles webhook ingestion.

GitHub push events can trigger durable codebase-analysis work after the ingestion stage.

## Integration principle

Provider identifiers must never be treated as globally interchangeable tenant identifiers. Every provider event must resolve to exactly one company or be rejected/quarantined.

## Future integrations

Jira/Linear and other sources are product hypotheses until a customer workflow demonstrates that their data materially improves context acquisition.
