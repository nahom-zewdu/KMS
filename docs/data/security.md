# Data Security

**Last audited:** 2026-11-14  
**Active Supabase project:** `iqafzuthrjfykfxndres`  
**Audit mode:** read-only catalog, grants, function, data-integrity, and Security Advisor inspection

## Current security status

<badge>CRITICAL — remediation required</badge>

The active project is not currently safe for multi-tenant customer data. Security Advisor reports 11 public tables with RLS disabled. Direct catalog inspection confirms broad `anon` and `authenticated` table privileges on these objects:

- `events`
- `raw_data`
- `edges`
- `contributions`
- `pull_requests`
- `issues`
- `query_logs`
- `repositories`
- `codebase_files`
- `file_entity_links`
- `codebase_modules`

Additional confirmed policy issues:
- `company_members`: public self-insert policy (`auth.uid() = user_id`) and self-update policy with no restrictive `WITH CHECK`. This can allow self-enrollment or self-role escalation.
- `entities`: two permissive `FOR ALL USING (true)` policies.
- `playbooks`: permissive public `FOR ALL USING (true)` policy.
- `companies`: public `SELECT USING (true)`.
- `company_integrations`: broad browser-role grants despite storing provider credentials and secrets.

Sensitive RPCs:
- `match_documents(vector,double precision,integer,text)`: browser roles can execute; company filter is optional; search_path is mutable.
- `search_edges_by_entity(text,text[])`: browser roles can execute; no company filter; search_path is mutable; live signature differs from current Python caller.
- `reconcile_repository_files(uuid,text,text[])`: browser roles can execute and repository/company ownership is not verified before deleting rows.
- `replace_implementation_edges(text,uuid[],jsonb)`: browser roles can execute; intended for trusted indexer only.

These are potential unauthorized access/privilege-escalation paths, not evidence that an attack or data exfiltration occurred.

## Data-integrity audit snapshot

| Data | Rows | Finding |
|---|---:|---|
| Companies | 2 | — |
| Company memberships | 2 | Both admin |
| Entities | 422 | No null/default company IDs |
| Edges | 611 | No null company IDs or cross-company endpoints |
| Raw data | 153 | No null/default company IDs |
| Events | 149 | No null/default company IDs |
| Codebase files | 237 | All reference existing repositories |
| Codebase modules | 96 | All reference existing repositories |
| File/entity links | 0 | — |
| Contributions | 0 | Live table lacks `company_id`, while current application expects it |

This snapshot is dated and must not be used as a live metric.

## Required access model

- Browser `anon`: no access to tenant-owned tables, credentials, graph/event data, or sensitive RPCs.
- Browser `authenticated`: only company membership-scoped reads and explicitly authorized membership/admin writes.
- Trusted Go/Python workers: service-role access, always with company predicates in application queries and RPC contracts.
- Next.js server admin client: only after verified user identity, explicit company membership, and role checks; never expose its key to the browser.
- Webhooks: enter through signature-validated backend endpoints, never through direct browser table access.

RLS is defense in depth, not a replacement for tenant predicates in privileged service-role queries. Every `SECURITY DEFINER` function must have a fixed safe search_path, minimal body, and explicit execute grants.

## Remediation status

- [x] Live audit and Security Advisor inspection completed.
- [x] Frontend codebase route now requires authentication and active-company repository scope on the KRT branch.
- [x] Frontend integrations route uses server-only admin access after membership/role checks.
- [x] Legacy role-slug onboarding page now requires authentication and active-company scope.
- [x] Authored `supabase/migrations/20261114150000_enforce_company_tenant_isolation.sql` to replace permissive policies, enforce tenant FKs/composite references, restrict browser grants, and harden RPCs. **Not applied or runtime-verified yet.**
- [x] Expanded `schema/tests/tenant_rls.sql` to include the KRT migration and anon/authenticated/service-role assertions. **Not executed yet.**
- [x] Frontend KRT branch now also signs/binds Slack OAuth state and verifies the initiating user/admin membership on callback; company switching verifies membership.
- [ ] Run the expanded SQL harness on disposable PostgreSQL with pgvector available and resolve any failures.
- [ ] Run frontend lint/build and backend test suites; perform full diff review.
- [ ] Apply reviewed migration to live Supabase only after disposable verification and explicit deployment approval; re-run Advisors and role-based live checks.

No live database DDL or data changes have been applied as part of this audit.

## Related documents

- `docs/development/roadmap.md` — canonical progress ledger.
- `docs/development/milestones/2026-11-14-knowledge-reliability.md` — KRT workstream plan and audit log.
- `docs/architecture/knowledge-reliability.md` — knowledge pipeline architecture.
- `schema/migrations/20261031_tenant_access_policies.sql` — historical intended policy migration; do not assume it is deployed or fully correct for the current live schema.
- `schema/tests/tenant_rls.sql` — expanded disposable PostgreSQL tenant policy harness; execution is still pending.
- `supabase/migrations/20261114150000_enforce_company_tenant_isolation.sql` — authored remediation migration; not yet applied to live Supabase.
