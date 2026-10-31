-- Migration: 20261031_tenant_guardrails.sql
-- Purpose: enforce tenant validation and reject the shared default company in company-scoped data paths.

BEGIN;

-- Prevent accidental writes to the shared default company in tenant-scoped tables.
ALTER TABLE public.companies
  ALTER COLUMN id DROP DEFAULT;

ALTER TABLE public.company_members
  ADD CONSTRAINT company_members_company_id_not_default CHECK (company_id IS NOT NULL AND company_id <> 'default');

ALTER TABLE public.company_integrations
  ADD CONSTRAINT company_integrations_company_id_not_default CHECK (company_id IS NOT NULL AND company_id <> 'default');

ALTER TABLE public.company_repos
  ADD CONSTRAINT company_repos_company_id_not_default CHECK (company_id IS NOT NULL AND company_id <> 'default');

ALTER TABLE public.ramp_plans
  ADD CONSTRAINT ramp_plans_company_id_not_default CHECK (company_id IS NOT NULL AND company_id <> 'default');

ALTER TABLE public.ramp_step_progress
  ADD CONSTRAINT ramp_step_progress_company_id_not_default CHECK (company_id IS NOT NULL AND company_id <> 'default');

ALTER TABLE public.entities
  ADD CONSTRAINT entities_company_id_not_default CHECK (company_id IS NOT NULL AND company_id <> 'default');

ALTER TABLE public.edges
  ADD CONSTRAINT edges_company_id_not_default CHECK (company_id IS NOT NULL AND company_id <> 'default');

-- Keep this as a strict invariant for all future tenant-scoped payloads.
CREATE OR REPLACE FUNCTION public.assert_real_company(company_id text)
RETURNS boolean
LANGUAGE sql
AS $$
  SELECT company_id IS NOT NULL
    AND btrim(company_id) <> ''
    AND lower(btrim(company_id)) <> 'default';
$$;

-- Example usage for future writes: the backend should validate before insert/update.
-- CREATE POLICY ... USING (public.assert_real_company(company_id));

COMMIT;
