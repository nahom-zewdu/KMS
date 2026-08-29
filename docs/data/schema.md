# Data Schema

## Authority

The live Supabase/Postgres schema is the runtime source of truth. The checked-in `schema/schemas.sql` is a stale bootstrap snapshot and must not be treated as an exact description of the deployed database.

## Core domains

### Identity and tenancy

- `companies`
- `company_members`
- `company_integrations`
- `company_repos`
- `profiles`

### Ingestion and knowledge

- `events`
- `raw_data`
- `entities`
- `edges`
- `repositories`
- `codebase_files`
- `codebase_modules`
- `file_entity_links`
- `contributions`
- `pull_requests`
- `issues`
- `query_logs`

### Product

- `playbooks`
- `ramp_plans`

## Important invariant

Tenant-owned records must carry a company scope where the domain requires it. Entity/relation identifiers and uniqueness rules must not accidentally permit cross-company collisions.

## Schema maintenance direction

The repository should eventually establish a versioned migration history from a captured live-schema baseline. Do not overwrite the live truth with the old reset script or make ad-hoc declaration edits without a migration plan.
