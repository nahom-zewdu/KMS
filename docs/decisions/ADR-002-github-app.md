# ADR-002: GitHub App Integration

## Status
Accepted

## Context

KMS needs repository access and webhook events while preserving company-level installation boundaries.

## Decision

Use a GitHub App as the integration mechanism. Installation identity is the authoritative signal for mapping incoming webhook events to a company when available.

## Consequences

The frontend owns the installation/callback experience while the backend owns webhook verification and ingestion. Repository selection and installation state must remain company-scoped.

## Security constraint

A provider owner/login lookup must not silently override a valid installation mapping. Conflicting mappings must be rejected rather than guessed.
