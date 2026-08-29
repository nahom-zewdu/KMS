# Data Security

## Current state

The live Supabase project has RLS enabled on core identity/product tables such as companies, company_members, company_integrations, entities, playbooks, profiles, and ramp_plans. Several ingestion/knowledge tables currently do not have RLS enabled.

This is a known security gap, not a claim that the current public data access model is safe by default.

## Required model

The eventual access model should distinguish:

- authenticated browser users accessing only companies they belong to;
- server-side workers using privileged credentials for ingestion and processing;
- provider webhooks entering only through verified backend endpoints.

Authorization must be company-membership based. `authenticated` alone is not sufficient authorization, and client-supplied `company_id` must not be trusted as proof of access.

## Credentials

Service-role credentials belong only in trusted server-side processes. They must never be exposed to the browser.

## Follow-up

Before directly exposing currently unprotected knowledge/ingestion tables through the Supabase Data API, design and test membership-based RLS policies and verify every affected frontend/backend access path.
