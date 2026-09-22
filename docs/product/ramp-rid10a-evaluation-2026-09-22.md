# RID-10A — Behavioral Candidate Projection

**Status:** IMPLEMENTED — read-only evaluation layer  
**Date:** 2026-09-22

## Objective

Test whether existing RID-09 route → handler → direct-operation evidence can be represented as bounded candidate evidence without changing production Ramp generation.

## Scope

The projector converts ComposedRouteEvidence into BehavioralCandidateEvidence.

It preserves:
- HTTP method and path
- concrete handler symbol and source file
- directly called handler field and operation
- route/call provenance
- next inspection target
- separate branch operations

It does not:
- modify WorkflowDiscoverer
- modify candidate scoring or selection
- write graph/Ramp/Supabase data
- infer interface implementations
- claim runtime ordering
- infer ownership or contribution safety
- merge branches
- add path/module keyword heuristics

## Candidate contract

Each projected unit has evidence type: ROUTE_HANDLER_DIRECT_OPERATION.

It produces a source-grounded statement:
METHOD path is registered to Handler, which directly calls field.Operation.

This is intentionally a statement about source evidence, not a claim that the complete runtime workflow has been recovered.

## Expected examples

GitHub:
POST /github → GitHubHandler.HandleGitHubWebhook → githubIngest.IngestGitHubEvent

Baseline:
GET /github/sync-baseline → CodebaseHandler.SyncBaseline → codebaseService.SyncRepository

Slack remains branch-specific:
POST /slack/events → SlackHandler.HandleSlackWebhook → slackBot.HandleEvent

and separately:
POST /slack/events → SlackHandler.HandleSlackWebhook → slackIngest.IngestSlackEvent

Query remains a transport boundary:
POST /query → QueryHandler.HandleQuery → redis.Subscribe

and:
POST /query → QueryHandler.HandleQuery → redis.Publish

## Verification gate

Focused tests cover GitHub projection, Slack branch preservation, Query transport evidence, deterministic ordering, empty input, and distinct source boundaries.

## Decision gate

This implementation is not production integration.

After local verification, evaluate projected behavioral units against existing IMPORTS candidates using:
1. Recognition
2. Behavioral grounding
3. Distinctness
4. Actionability
5. Evidence sufficiency

Only after that comparison should behavioral candidates enter production Ramp selection.
