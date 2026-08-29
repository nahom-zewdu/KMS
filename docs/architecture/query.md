# Query Architecture

## Current path

The Go backend exposes `/query` and bridges user queries into the asynchronous query workflow. The Python side contains the query engine and publishes results for the requesting integration/client.

The historical overview describes a simple ILIKE-based query path and lists vector and graph retrieval as later work. Current implementation must be inspected before claiming any particular retrieval strategy is complete.

## Intended retrieval model

The product direction is to combine:

1. semantic retrieval from company-scoped knowledge;
2. graph/context retrieval where relationships materially improve the answer;
3. ranking and source attribution;
4. an LLM response grounded in retrieved evidence.

These are product/architecture targets, not claims that every part is currently implemented.

## Invariants

- Query context must remain company-scoped.
- Retrieved evidence should be attributable to stored company data.
- The system should distinguish insufficient evidence from a confident answer.
- Authorization must not depend on a client-supplied company ID alone.
