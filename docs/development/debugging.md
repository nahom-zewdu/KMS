# Debugging Guide

## Start from the boundary

When a feature fails, trace the request/job lifecycle rather than guessing at the final symptom:

```text
Frontend/request
  -> Go handler
  -> Supabase / Redis
  -> Python consumer
  -> NLP/domain operation
  -> persistence
```

Identify the first boundary where the expected state stops being true.

## Redis worker issues

Check the stream, consumer group, pending entries, and handler exception. A processing failure should not be mistaken for successful acknowledgement.

## Supabase issues

Verify the live table/column shape and RLS state before changing application code. The checked-in schema snapshot is known to be stale.

## Tenant issues

Log safe identifiers needed to trace company resolution, but never log provider secrets, webhook signatures, access tokens, private keys, or service-role credentials.

## Slow Python startup

Import-time work can dominate startup. Isolate imports and expensive initialization with small timing probes before optimizing application logic.

## General rule

Prefer a minimal reproduction and a failing test over repeated speculative edits. Once the root cause is confirmed, make the smallest change that restores the intended invariant.
