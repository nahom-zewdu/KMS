-- Tenant invariants for the existing KMS schema.
-- This migration never remaps or deletes historical rows. It aborts with a table-specific
-- error if existing data cannot satisfy the invariant, so operators can review a backfill first.

BEGIN;

ALTER TABLE public.companies ALTER COLUMN id DROP DEFAULT;
ALTER TABLE public.raw_data ADD COLUMN IF NOT EXISTS company_id text;

DO $$
DECLARE
  table_name text;
  has_invalid_rows boolean;
  tenant_tables text[] := ARRAY[
    'company_members',
    'company_integrations',
    'company_repos',
    'repositories',
    'ramp_plans',
    'ramp_step_progress',
    'entities',
    'edges',
    'raw_data'
  ];
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns AS columns
    WHERE columns.table_schema = 'public'
      AND columns.table_name = 'profiles'
      AND columns.column_name = 'company_id'
  ) THEN
    ALTER TABLE public.profiles ALTER COLUMN company_id DROP DEFAULT;
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.companies
    WHERE id IS NULL OR btrim(id) = '' OR lower(btrim(id)) = 'default'
  ) THEN
    RAISE EXCEPTION
      'public.companies contains NULL, blank, or default ids; review existing company data before retrying';
  END IF;

  FOREACH table_name IN ARRAY tenant_tables LOOP
    IF to_regclass(format('public.%I', table_name)) IS NULL THEN
      RAISE EXCEPTION 'required tenant table public.% is missing; migration is not safe to apply', table_name;
    END IF;

    EXECUTE format(
      'SELECT EXISTS (SELECT 1 FROM public.%I WHERE company_id IS NULL OR btrim(company_id) = '''' OR lower(btrim(company_id)) = ''default'')',
      table_name
    ) INTO has_invalid_rows;

    IF has_invalid_rows THEN
      RAISE EXCEPTION
        'public.% contains NULL, blank, or default company_id rows; review and explicitly map existing data before retrying',
        table_name;
    END IF;

    EXECUTE format(
      'SELECT EXISTS (SELECT 1 FROM public.%I t WHERE NOT EXISTS (SELECT 1 FROM public.companies c WHERE c.id = t.company_id))',
      table_name
    ) INTO has_invalid_rows;
    IF has_invalid_rows THEN
      RAISE EXCEPTION
        'public.% contains company_id values without a matching public.companies row; review existing data before retrying',
        table_name;
    END IF;
  END LOOP;

  IF EXISTS (
    SELECT 1
    FROM public.edges edge
    JOIN public.entities source_entity ON source_entity.id = edge.source_id
    JOIN public.entities target_entity ON target_entity.id = edge.target_id
    WHERE source_entity.company_id <> edge.company_id
       OR target_entity.company_id <> edge.company_id
  ) THEN
    RAISE EXCEPTION
      'public.edges contains cross-company endpoints; review and repair these rows before retrying';
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public'
      AND t.relname = 'companies'
      AND c.conname = 'companies_id_not_default'
  ) THEN
    ALTER TABLE public.companies
      ADD CONSTRAINT companies_id_not_default
      CHECK (btrim(id) <> '' AND lower(btrim(id)) <> 'default') NOT VALID;
  END IF;
END $$;
ALTER TABLE public.companies VALIDATE CONSTRAINT companies_id_not_default;

ALTER TABLE public.company_members ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.company_integrations ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.company_repos ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.repositories ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.ramp_plans ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.ramp_step_progress ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.entities ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.edges ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.raw_data ALTER COLUMN company_id SET NOT NULL;

DO $$
DECLARE
  constraint_row text[];
  constraints_to_add text[][] := ARRAY[
    ARRAY['repositories', 'repositories_company_id_fkey', 'company_id'],
    ARRAY['ramp_plans', 'ramp_plans_company_id_fkey', 'company_id'],
    ARRAY['ramp_step_progress', 'ramp_step_progress_company_id_fkey', 'company_id'],
    ARRAY['entities', 'entities_company_id_fkey', 'company_id'],
    ARRAY['edges', 'edges_company_id_fkey', 'company_id'],
    ARRAY['raw_data', 'raw_data_company_id_fkey', 'company_id']
  ];
  table_name text;
  constraint_name text;
  column_name text;
BEGIN
  FOREACH constraint_row SLICE 1 IN ARRAY constraints_to_add LOOP
    table_name := constraint_row[1];
    constraint_name := constraint_row[2];
    column_name := constraint_row[3];
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint c
      JOIN pg_class t ON t.oid = c.conrelid
      JOIN pg_namespace n ON n.oid = t.relnamespace
      WHERE n.nspname = 'public' AND t.relname = table_name AND c.conname = constraint_name
    ) THEN
      EXECUTE format(
        'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES public.companies(id) NOT VALID',
        table_name, constraint_name, column_name
      );
    END IF;
  END LOOP;
END $$;

ALTER TABLE public.repositories VALIDATE CONSTRAINT repositories_company_id_fkey;
ALTER TABLE public.ramp_plans VALIDATE CONSTRAINT ramp_plans_company_id_fkey;
ALTER TABLE public.ramp_step_progress VALIDATE CONSTRAINT ramp_step_progress_company_id_fkey;
ALTER TABLE public.entities VALIDATE CONSTRAINT entities_company_id_fkey;
ALTER TABLE public.edges VALIDATE CONSTRAINT edges_company_id_fkey;
ALTER TABLE public.raw_data VALIDATE CONSTRAINT raw_data_company_id_fkey;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public' AND t.relname = 'entities'
      AND c.conname = 'entities_id_company_id_key'
  ) THEN
    ALTER TABLE public.entities
      ADD CONSTRAINT entities_id_company_id_key UNIQUE (id, company_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public' AND t.relname = 'edges'
      AND c.conname = 'edges_source_company_fkey'
  ) THEN
    ALTER TABLE public.edges
      ADD CONSTRAINT edges_source_company_fkey
      FOREIGN KEY (source_id, company_id)
      REFERENCES public.entities(id, company_id) NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public' AND t.relname = 'edges'
      AND c.conname = 'edges_target_company_fkey'
  ) THEN
    ALTER TABLE public.edges
      ADD CONSTRAINT edges_target_company_fkey
      FOREIGN KEY (target_id, company_id)
      REFERENCES public.entities(id, company_id) NOT VALID;
  END IF;
END $$;

ALTER TABLE public.edges VALIDATE CONSTRAINT edges_source_company_fkey;
ALTER TABLE public.edges VALIDATE CONSTRAINT edges_target_company_fkey;

DO $$
DECLARE
  table_name text;
  constraint_name text;
  tenant_tables text[] := ARRAY[
    'company_members',
    'company_integrations',
    'company_repos',
    'repositories',
    'ramp_plans',
    'ramp_step_progress',
    'entities',
    'edges',
    'raw_data'
  ];
BEGIN
  FOREACH table_name IN ARRAY tenant_tables LOOP
    constraint_name := table_name || '_company_id_not_default';
    IF NOT EXISTS (
      SELECT 1
      FROM pg_constraint c
      JOIN pg_class t ON t.oid = c.conrelid
      JOIN pg_namespace n ON n.oid = t.relnamespace
      WHERE n.nspname = 'public'
        AND t.relname = table_name
        AND c.conname = constraint_name
    ) THEN
      EXECUTE format(
        'ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (company_id IS NOT NULL AND btrim(company_id) <> '''' AND lower(btrim(company_id)) <> ''default'') NOT VALID',
        table_name,
        constraint_name
      );
    END IF;
  END LOOP;
END $$;

ALTER TABLE public.company_members VALIDATE CONSTRAINT company_members_company_id_not_default;
ALTER TABLE public.company_integrations VALIDATE CONSTRAINT company_integrations_company_id_not_default;
ALTER TABLE public.company_repos VALIDATE CONSTRAINT company_repos_company_id_not_default;
ALTER TABLE public.repositories VALIDATE CONSTRAINT repositories_company_id_not_default;
ALTER TABLE public.ramp_plans VALIDATE CONSTRAINT ramp_plans_company_id_not_default;
ALTER TABLE public.ramp_step_progress VALIDATE CONSTRAINT ramp_step_progress_company_id_not_default;
ALTER TABLE public.entities VALIDATE CONSTRAINT entities_company_id_not_default;
ALTER TABLE public.edges VALIDATE CONSTRAINT edges_company_id_not_default;
ALTER TABLE public.raw_data VALIDATE CONSTRAINT raw_data_company_id_not_default;

CREATE OR REPLACE FUNCTION public.assert_real_company(company_id text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT company_id IS NOT NULL
    AND btrim(company_id) <> ''
    AND lower(btrim(company_id)) <> 'default';
$$;

COMMIT;
