# Data Schema

> Current-state snapshot: live Supabase project `iqafzuthrjfykfxndres`, checked 2026-08-30.

## Authority

The live Supabase/Postgres schema is the runtime source of truth. The checked-in `schema/schemas.sql` is an older reset/bootstrap snapshot and is not a faithful representation of the deployed database.

The live database currently contains 20 public tables. Important product/data domains are:

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

## Verified live fields that matter to the current system

The live schema includes fields added after the old bootstrap snapshot, including:

- `events.company_id`
- `raw_data.company_id`, `embedding`, `embedding_model`
- `entities.company_id`
- `edges.company_id`, `confidence`, `source_record_id`, `last_seen_at`, `expires_at`
- `repositories.company_id`
- `codebase_files.company_id`, `module_path`, `importance_score`
- `codebase_modules.company_id`
- extended GitHub installation fields on `company_integrations`
- `ramp_plans` for persisted First 7 Days plans

## Current live data snapshot

At reconciliation time the database contained approximately:

| Table | Rows |
|---|---:|
| `companies` | 2 |
| `company_members` | 2 |
| `company_integrations` | 2 |
| `company_repos` | 0 |
| `ramp_plans` | 1 |
| `repositories` | 1 |
| `codebase_files` | 72 |
| `entities` | 88 |
| `edges` | 124 |
| `events` | 8 |
| `raw_data` | 12 |

There is therefore real knowledge/codebase data in the current database; the product should be tested against this existing state rather than treated as an empty theoretical system.

## Important constraints

`repositories.full_name` is currently globally unique in the live database even though application logic scopes repository lookup by company. This is a known schema/application mismatch and should be handled through a deliberate migration, not an ad-hoc declaration edit.

Tenant-owned records must carry company scope where the domain requires it. Deterministic identifiers and uniqueness rules must also remain company-safe.

## Schema maintenance direction

The repository should eventually establish a versioned migration history from a captured live-schema baseline. Do not overwrite the live truth with the old reset script or make declaration-only edits without a migration plan.
