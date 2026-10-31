\set ON_ERROR_STOP on

-- Run only against an empty, disposable PostgreSQL database:
-- psql "$TEST_DATABASE_URL" -f schema/tests/tenant_rls.sql

CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN BYPASSRLS;

CREATE SCHEMA auth;
CREATE TABLE auth.users (id uuid PRIMARY KEY);
CREATE FUNCTION auth.uid()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
GRANT USAGE ON SCHEMA auth TO authenticated;
GRANT EXECUTE ON FUNCTION auth.uid() TO authenticated, service_role;

CREATE TABLE public.companies (id text PRIMARY KEY DEFAULT 'default', name text NOT NULL);
CREATE TABLE public.company_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  company_id text REFERENCES public.companies(id),
  role text NOT NULL CHECK (role IN ('admin','manager','member')),
  is_owner boolean DEFAULT false,
  UNIQUE(user_id, company_id)
);
CREATE TABLE public.company_integrations (id uuid PRIMARY KEY, company_id text REFERENCES public.companies(id), provider text, access_token text);
CREATE TABLE public.company_repos (id uuid PRIMARY KEY, company_id text REFERENCES public.companies(id), full_name text);
CREATE TABLE public.repositories (id uuid PRIMARY KEY, company_id text, full_name text);
CREATE TABLE public.codebase_files (id uuid PRIMARY KEY, repository_id uuid REFERENCES public.repositories(id), file_path text);
CREATE TABLE public.codebase_modules (id uuid PRIMARY KEY, repository_id uuid REFERENCES public.repositories(id), module_path text);
CREATE TABLE public.file_entity_links (id uuid PRIMARY KEY, file_id uuid REFERENCES public.codebase_files(id), entity_id uuid);
CREATE TABLE public.entities (id uuid PRIMARY KEY, company_id text, type text, name text, metadata jsonb);
CREATE TABLE public.edges (id uuid PRIMARY KEY, company_id text, source_id uuid REFERENCES public.entities(id), target_id uuid REFERENCES public.entities(id), type text, metadata jsonb, confidence double precision);
CREATE TABLE public.raw_data (id uuid PRIMARY KEY, company_id text, content text, event_id uuid);
CREATE TABLE public.playbooks (id uuid PRIMARY KEY, company_id text, role text);
CREATE TABLE public.ramp_plans (id uuid PRIMARY KEY, company_id text, role text);
CREATE TABLE public.ramp_step_progress (id uuid PRIMARY KEY, plan_id uuid, company_id text, user_id text, step_id text, status text);
CREATE TABLE public.events (
  id uuid PRIMARY KEY,
  source text NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  delivery_id text UNIQUE,
  processed boolean DEFAULT false,
  truncated boolean DEFAULT false,
  created_at timestamptz DEFAULT now()
);
CREATE TABLE public.contributions (
  id uuid PRIMARY KEY,
  person_name text NOT NULL,
  repo_name text NOT NULL,
  commit_count integer DEFAULT 0,
  pr_count integer DEFAULT 0,
  issue_count integer DEFAULT 0,
  bus_factor double precision DEFAULT 0,
  updated_at timestamptz DEFAULT now(),
  UNIQUE(person_name, repo_name)
);
CREATE TABLE public.pull_requests (id uuid PRIMARY KEY);
CREATE TABLE public.issues (id uuid PRIMARY KEY);
CREATE TABLE public.query_logs (id uuid PRIMARY KEY);

\ir ../migrations/20261031_tenant_guardrails.sql
\ir ../migrations/20261031_tenant_guardrails.sql

INSERT INTO auth.users VALUES
  ('00000000-0000-0000-0000-000000000001'),
  ('00000000-0000-0000-0000-000000000002'),
  ('00000000-0000-0000-0000-000000000003');
INSERT INTO public.companies VALUES ('company-a','Company A'),('company-b','Company B');
INSERT INTO public.events (id,source,event_type,payload,delivery_id)
VALUES ('70000000-0000-0000-0000-000000000001','github','push','{}','delivery-global-1');
INSERT INTO public.raw_data (id,company_id,content,event_id)
VALUES ('71000000-0000-0000-0000-000000000001','company-a','linked historical event','70000000-0000-0000-0000-000000000001');
INSERT INTO public.repositories VALUES
  ('50000000-0000-0000-0000-000000000001','company-a','org/repo-a');
INSERT INTO public.contributions (id, person_name, repo_name, commit_count)
VALUES ('60000000-0000-0000-0000-000000000001','engineer','org/repo-a',3);
\ir ../migrations/20261101_contributions_tenant_scope.sql
\ir ../migrations/20261101_contributions_tenant_scope.sql
\ir ../migrations/20261101_events_company_scope.sql
\ir ../migrations/20261101_events_company_scope.sql
INSERT INTO public.company_members VALUES
  ('10000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000001','company-a','admin',true),
  ('10000000-0000-0000-0000-000000000002','00000000-0000-0000-0000-000000000002','company-a','member',false),
  ('10000000-0000-0000-0000-000000000003','00000000-0000-0000-0000-000000000003','company-b','admin',true);
INSERT INTO public.entities VALUES
  ('20000000-0000-0000-0000-000000000001','company-a','SERVICE','A data','{}'),
  ('20000000-0000-0000-0000-000000000002','company-b','SERVICE','B data','{}');
INSERT INTO public.edges VALUES
  ('30000000-0000-0000-0000-000000000001','company-a','20000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','SELF','{}',0.9),
  ('30000000-0000-0000-0000-000000000002','company-b','20000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000002','SELF','{}',0.9);
INSERT INTO public.raw_data (id, company_id, content) VALUES
  ('40000000-0000-0000-0000-000000000001','company-a','A history'),
  ('40000000-0000-0000-0000-000000000002','company-b','B history');

\ir ../migrations/20261031_tenant_access_policies.sql
\ir ../migrations/20261031_tenant_access_policies.sql
\ir ../graph_traverser_rpc.sql

SET ROLE authenticated;
SET request.jwt.claim.sub = '00000000-0000-0000-0000-000000000001';
DO $$ DECLARE row_count integer; BEGIN
  SELECT count(*) INTO row_count FROM public.entities;
  IF row_count <> 1 THEN RAISE EXCEPTION 'cross-company entity read: expected 1 got %', row_count; END IF;
  SELECT count(*) INTO row_count FROM public.edges;
  IF row_count <> 1 THEN RAISE EXCEPTION 'cross-company edge read: expected 1 got %', row_count; END IF;
  SELECT count(*) INTO row_count FROM public.raw_data;
  IF row_count <> 1 THEN RAISE EXCEPTION 'cross-company raw_data read: expected 1 got %', row_count; END IF;
  SELECT count(*) INTO row_count FROM public.company_members;
  IF row_count <> 2 THEN RAISE EXCEPTION 'membership visibility or recursive policy failure: expected 2 got %', row_count; END IF;
  SELECT count(*) INTO row_count
  FROM public.search_edges_by_entity('A data', ARRAY[]::text[], 'company-a');
  IF row_count <> 1 THEN RAISE EXCEPTION 'company-scoped graph RPC expected 1 row, got %', row_count; END IF;
  SELECT count(*) INTO row_count
  FROM public.search_edges_by_entity('B data', ARRAY[]::text[], 'company-b');
  IF row_count <> 0 THEN RAISE EXCEPTION 'cross-company graph RPC returned % rows', row_count; END IF;
END $$;
DO $$ BEGIN
  BEGIN
    INSERT INTO public.company_members (id,user_id,company_id,role,is_owner)
    VALUES ('10000000-0000-0000-0000-000000000004', auth.uid(), 'company-b', 'admin', true);
    RAISE EXCEPTION 'self-insertion unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
DO $$ DECLARE row_count integer; BEGIN
  BEGIN
    INSERT INTO public.entities (id,company_id,type,name,metadata)
    VALUES ('20000000-0000-0000-0000-000000000003','company-b','SERVICE','forbidden','{}');
    RAISE EXCEPTION 'authenticated tenant write unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    INSERT INTO public.raw_data (id,company_id,content)
    VALUES ('40000000-0000-0000-0000-000000000004','company-b','forbidden');
    RAISE EXCEPTION 'authenticated raw_data write unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;

SET request.jwt.claim.sub = '00000000-0000-0000-0000-000000000002';
DO $$ DECLARE row_count integer; BEGIN
  UPDATE public.company_members SET role = 'admin'
  WHERE user_id = auth.uid() AND company_id = 'company-a';
  GET DIAGNOSTICS row_count = ROW_COUNT;
  IF row_count <> 0 THEN RAISE EXCEPTION 'membership self-promotion unexpectedly updated % rows', row_count; END IF;
END $$;

SET request.jwt.claim.sub = '00000000-0000-0000-0000-000000000001';
SELECT public.create_company_with_owner('company-c','Company C');
DO $$ DECLARE row_count integer; BEGIN
  SELECT count(*) INTO row_count FROM public.company_members
  WHERE company_id='company-c' AND user_id=auth.uid() AND role='admin' AND is_owner;
  IF row_count <> 1 THEN RAISE EXCEPTION 'company owner membership was not created'; END IF;
END $$;

RESET ROLE;
SET ROLE authenticated;
SET request.jwt.claim.sub = '00000000-0000-0000-0000-000000000003';
DO $$ DECLARE row_count integer; BEGIN
  UPDATE public.company_members SET role = 'admin'
  WHERE user_id = '00000000-0000-0000-0000-000000000002' AND company_id = 'company-a';
  GET DIAGNOSTICS row_count = ROW_COUNT;
  IF row_count <> 0 THEN RAISE EXCEPTION 'cross-company unauthorized role update affected % rows', row_count; END IF;
END $$;

RESET ROLE;
SET ROLE service_role;
DO $$ DECLARE row_count integer; BEGIN
  SELECT count(*) INTO row_count FROM public.entities;
  IF row_count <> 2 THEN RAISE EXCEPTION 'service role should access both tenants; got %', row_count; END IF;
  INSERT INTO public.raw_data (id, company_id, content)
  VALUES ('40000000-0000-0000-0000-000000000003','company-b','worker write');
  SELECT count(*) INTO row_count FROM public.contributions
  WHERE company_id = 'company-a' AND repo_name = 'org/repo-a';
  IF row_count <> 1 THEN RAISE EXCEPTION 'historical contribution company mapping failed'; END IF;
  SELECT count(*) INTO row_count
  FROM information_schema.columns
  WHERE table_schema='public' AND table_name='events'
    AND column_name='company_id' AND is_nullable='NO';
  IF row_count <> 1 THEN RAISE EXCEPTION 'events company_id column is missing or nullable'; END IF;
  SELECT count(*) INTO row_count FROM public.events
  WHERE id='70000000-0000-0000-0000-000000000001'
    AND company_id='company-a';
  IF row_count <> 1 THEN RAISE EXCEPTION 'historical event company mapping failed'; END IF;
  BEGIN
    INSERT INTO public.events (id,company_id,source,event_type,payload,delivery_id)
    VALUES ('70000000-0000-0000-0000-000000000002','company-b','github','push','{}','delivery-global-1');
    RAISE EXCEPTION 'cross-company duplicate delivery_id unexpectedly succeeded';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;
RESET ROLE;

SELECT 'tenant RLS integration tests passed' AS result;
