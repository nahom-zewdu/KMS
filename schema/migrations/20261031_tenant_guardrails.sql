-- Migration: 20261031_tenant_guardrails.sql
-- Purpose: enforce tenant validation and reject the shared default company in company-scoped data paths.
-- This migration is intentionally conservative: it fails fast when historical rows still use the default tenant.

BEGIN;

-- Remove the shared default from the canonical company identifier source.
ALTER TABLE public.companies
  ALTER COLUMN id DROP DEFAULT;

-- Fail fast if any existing company-scoped rows still use the default tenant. This avoids silently deleting data in production.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM public.companies WHERE id IS NULL OR lower(btrim(id)) = 'default') THEN
    RAISE EXCEPTION 'shared default company still exists in companies; clean this data before applying tenant guardrails';
  END IF;
  IF EXISTS (SELECT 1 FROM public.company_members WHERE company_id IS NULL OR lower(btrim(company_id)) = 'default') THEN
    RAISE EXCEPTION 'shared default company still exists in company_members; clean this data before applying tenant guardrails';
  END IF;
  IF EXISTS (SELECT 1 FROM public.company_integrations WHERE company_id IS NULL OR lower(btrim(company_id)) = 'default') THEN
    RAISE EXCEPTION 'shared default company still exists in company_integrations; clean this data before applying tenant guardrails';
  END IF;
  IF EXISTS (SELECT 1 FROM public.company_repos WHERE company_id IS NULL OR lower(btrim(company_id)) = 'default') THEN
    RAISE EXCEPTION 'shared default company still exists in company_repos; clean this data before applying tenant guardrails';
  END IF;
  IF EXISTS (SELECT 1 FROM public.ramp_plans WHERE company_id IS NULL OR lower(btrim(company_id)) = 'default') THEN
    RAISE EXCEPTION 'shared default company still exists in ramp_plans; clean this data before applying tenant guardrails';
  END IF;
  IF EXISTS (SELECT 1 FROM public.ramp_step_progress WHERE company_id IS NULL OR lower(btrim(company_id)) = 'default') THEN
    RAISE EXCEPTION 'shared default company still exists in ramp_step_progress; clean this data before applying tenant guardrails';
  END IF;
END $$;

ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_repos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ramp_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ramp_step_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.edges ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.company_members
  ADD CONSTRAINT company_members_company_id_not_default CHECK (company_id IS NOT NULL AND btrim(company_id) <> '' AND lower(btrim(company_id)) <> 'default');

ALTER TABLE public.company_integrations
  ADD CONSTRAINT company_integrations_company_id_not_default CHECK (company_id IS NOT NULL AND btrim(company_id) <> '' AND lower(btrim(company_id)) <> 'default');

ALTER TABLE public.company_repos
  ADD CONSTRAINT company_repos_company_id_not_default CHECK (company_id IS NOT NULL AND btrim(company_id) <> '' AND lower(btrim(company_id)) <> 'default');

ALTER TABLE public.ramp_plans
  ADD CONSTRAINT ramp_plans_company_id_not_default CHECK (company_id IS NOT NULL AND btrim(company_id) <> '' AND lower(btrim(company_id)) <> 'default');

ALTER TABLE public.ramp_step_progress
  ADD CONSTRAINT ramp_step_progress_company_id_not_default CHECK (company_id IS NOT NULL AND btrim(company_id) <> '' AND lower(btrim(company_id)) <> 'default');

ALTER TABLE public.entities
  ADD CONSTRAINT entities_company_id_not_default CHECK (company_id IS NOT NULL AND btrim(company_id) <> '' AND lower(btrim(company_id)) <> 'default');

ALTER TABLE public.edges
  ADD CONSTRAINT edges_company_id_not_default CHECK (company_id IS NOT NULL AND btrim(company_id) <> '' AND lower(btrim(company_id)) <> 'default');

CREATE OR REPLACE FUNCTION public.assert_real_company(company_id text)
RETURNS boolean
LANGUAGE sql
AS $$
  SELECT company_id IS NOT NULL
    AND btrim(company_id) <> ''
    AND lower(btrim(company_id)) <> 'default';
$$;

-- Example usage for future writes: the backend should validate before insert/update and reject default company IDs.
-- CREATE POLICY ... USING (public.assert_real_company(company_id));

COMMIT;
