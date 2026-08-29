# Architecture Overview

## System boundary

KMS currently spans a Go backend, Python services/workers, Redis Streams, Supabase/Postgres, and a separate Next.js frontend repository.

```text
Slack / GitHub
      |
      v
Go API (`api/`)
   |       |
   v       v
Supabase  Redis Streams
             |
             v
       Python worker (`nlp/`)
        |     |      |
        v     v      v
       NER   RE   codebase analysis
        |     |
        +---> Supabase knowledge graph

Next.js frontend (`kms-frontend`)
   |
   +--> Auth/company workspace/integrations/Ramp
```

## Boundaries

- Go owns HTTP ingress, webhook verification, tenant resolution, and publication of durable work.
- Python owns NLP processing, graph construction, query/analysis services, and codebase processing.
- Supabase is the persistent data store and runtime schema authority.
- Redis Streams provide asynchronous work transport.
- The frontend is a separate repository and product surface.

## Architectural principle

The system should remain understandable and small while customer value is being validated. New infrastructure requires a concrete problem that the existing primitives cannot solve adequately.
