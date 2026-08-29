# ADR-001: Hybrid Go + Python Architecture

## Status
Accepted

## Context

KMS needs a reliable HTTP/webhook boundary while also using Python's NLP and analysis ecosystem.

## Decision

Keep Go as the HTTP/webhook and integration ingress layer and Python as the NLP/analysis worker and service layer. Redis Streams provide the asynchronous boundary between them.

## Consequences

This keeps provider-facing HTTP concerns separate from NLP dependencies and allows each runtime to evolve independently. It also creates an operational boundary that must be tested explicitly: payload contracts, failure semantics, tenant propagation, and stream processing.

## Rejected alternative

A single-runtime rewrite is not justified while the existing split provides a clear responsibility boundary and is already implemented.
