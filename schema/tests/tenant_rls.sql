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
CREATE TABLE public.profiles (id uuid PRIMARY KEY REFERENCES auth.users(id), name text);
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
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
CREATE TABLE public.edges (id uuid PRIMARY KEY, company_id text, source_id uuid REFERENCES public.entities(id), target_id uuid REFERENCES public.entities(id), type text, metadata jsonb, confidence double precision, created_at timestamptz DEFAULT now());
CREATE TABLE public.raw_data (
  id uuid PRIMARY KEY,
  company_id text NOT NULL,
  source text NOT NULL,
  content text NOT NULL,
  record_id text UNIQUE NOT NULL,
  event_id uuid,
  created_at timestamptz DEFAULT now()
);
CREATE TABLE public.playbooks (id uuid PRIMARY KEY, company_id text, role text);
CREATE TABLE public.ramp_plans (id uuid PRIMARY KEY, company_id text, role text);
CREATE TABLE public.ramp_step_progress (id uuid PRIMARY KEY, plan_id uuid, company_id text, user_id text, step_id text, status text);
CREATE TABLE public.ramp_step_feedback (id uuid PRIMARY KEY, plan_id uuid NOT NULL, company_id text NOT NULL, step_id text NOT NULL, user_id text NOT NULL, rating text NOT NULL, reason text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
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
INSERT INTO public.raw_data (id,company_id,source,content,record_id,event_id)
VALUES (
  '71000000-0000-0000-0000-000000000001',
  'company-a',
  'github',
  'linked historical event',
  'delivery-global-1',
  '70000000-0000-0000-0000-000000000001'
);
INSERT INTO public.repositories VALUES
  ('50000000-0000-0000-0000-000000000001','company-a','org/repo-a');
INSERT INTO public.contributions (id, person_name, repo_name, commit_count)
VALUES ('60000000-0000-0000-0000-000000000001','engineer','org/repo-a',3);
\ir ../migrations/20261101_contributions_tenant_scope.sql
\ir ../migrations/20261101_contributions_tenant_scope.sql
\ir ../migrations/20261101_events_company_scope.sql
\ir ../migrations/20261101_events_company_scope.sql
\ir ../migrations/20261101_ingestion_outbox.sql
\ir ../migrations/20261101_ingestion_outbox.sql
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
INSERT INTO public.raw_data (id, company_id, source, content, record_id) VALUES
  ('40000000-0000-0000-0000-000000000001','company-a','github','A history','a-history'),
  ('40000000-0000-0000-0000-000000000002','company-b','github','B history','b-history');

\ir ../migrations/20261031_tenant_access_policies.sql
\ir ../migrations/20261031_tenant_access_policies.sql
\ir ../graph_traverser_rpc.sql
\ir ../../supabase/migrations/20261114095928_add_repository_file_reconciliation_rpc.sql
\ir ../../supabase/migrations/20261114101649_add_implementation_edge_replacement_rpc.sql
\ir ../../supabase/migrations/20261114150000_enforce_company_tenant_isolation.sql

-- Anonymous browser role must not access tenant data or integration credentials.
SET ROLE anon;
DO $krt$ BEGIN
  BEGIN
    PERFORM count(*) FROM public.companies;
    RAISE EXCEPTION 'anon unexpectedly read companies';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    PERFORM count(*) FROM public.entities;
    RAISE EXCEPTION 'anon unexpectedly read entities';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    PERFORM count(*) FROM public.company_integrations;
    RAISE EXCEPTION 'anon unexpectedly read integration credentials';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $krt$;
RESET ROLE;


SET ROLE authenticated;
SET request.jwt.claim.sub = '00000000-0000-0000-0000-000000000001';
DO $krt$ BEGIN
  IF has_function_privilege('authenticated','public.search_edges_by_entity(text,text[],text)','EXECUTE') THEN
    RAISE EXCEPTION 'authenticated can execute graph search RPC';
  END IF;
  IF has_function_privilege('authenticated','public.reconcile_repository_files(uuid,text,text[])','EXECUTE') THEN
    RAISE EXCEPTION 'authenticated can execute repository reconciliation RPC';
  END IF;
  IF has_function_privilege('authenticated','public.replace_implementation_edges(text,uuid[],jsonb)','EXECUTE') THEN
    RAISE EXCEPTION 'authenticated can execute implementation edge replacement RPC';
  END IF;
  IF to_regprocedure('public.match_documents(extensions.vector,double precision,integer,text)') IS NOT NULL
     AND has_function_privilege('authenticated','public.match_documents(extensions.vector,double precision,integer,text)','EXECUTE') THEN
    RAISE EXCEPTION 'authenticated can execute vector search RPC';
  END IF;
  IF NOT has_function_privilege('service_role','public.search_edges_by_entity(text,text[],text)','EXECUTE') THEN
    RAISE EXCEPTION 'service_role cannot execute graph search RPC';
  END IF;
END $krt$;
DO $krt$ DECLARE row_count integer; BEGIN
  SELECT count(*) INTO row_count FROM public.entities;
  IF row_count <> 1 THEN RAISE EXCEPTION 'cross-company entity read: expected 1 got %', row_count; END IF;
  SELECT count(*) INTO row_count FROM public.companies;
  IF row_count <> 1 THEN RAISE EXCEPTION 'company directory scope expected 1 got %', row_count; END IF;
  SELECT count(*) INTO row_count FROM public.edges;
  IF row_count <> 1 THEN RAISE EXCEPTION 'cross-company edge read: expected 1 got %', row_count; END IF;
  IF has_table_privilege('authenticated','public.raw_data','SELECT') THEN
    RAISE EXCEPTION 'authenticated has direct raw_data SELECT privilege';
  END IF;
  SELECT count(*) INTO row_count FROM public.company_members;
  IF row_count <> 2 THEN RAISE EXCEPTION 'membership visibility or recursive policy failure: expected 2 got %', row_count; END IF;
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
    INSERT INTO public.raw_data (id, company_id, source, content, record_id)
    VALUES ('40000000-0000-0000-0000-000000000004','company-b','github','forbidden','forbidden');
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
  SELECT count(*) INTO row_count
  FROM public.search_edges_by_entity('A data', ARRAY[]::text[], 'company-a');
  IF row_count <> 1 THEN RAISE EXCEPTION 'company-scoped graph RPC expected 1 row, got %', row_count; END IF;
  SELECT count(*) INTO row_count
  FROM public.search_edges_by_entity('B data', ARRAY[]::text[], 'company-b');
  IF row_count <> 1 THEN RAISE EXCEPTION 'service-role graph RPC company filter failed, got %', row_count; END IF;
  INSERT INTO public.raw_data (id, company_id, source, content, record_id)
  VALUES ('40000000-0000-0000-0000-000000000003','company-b','github','worker write','worker-write');
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
DO $$
DECLARE
  first_outbox_id uuid;
  duplicate_outbox_id uuid;
  claimed_id uuid;
  persisted_count integer;
  success boolean;
BEGIN
  first_outbox_id := public.persist_ingestion_with_outbox(
    jsonb_build_object(
      'id','70000000-0000-0000-0000-000000000003',
      'company_id','company-a',
      'source','github',
      'event_type','push',
      'payload','{}'::jsonb,
      'delivery_id','outbox-delivery-1',
      'created_at',now()
    ),
    jsonb_build_object(
      'id','71000000-0000-0000-0000-000000000003',
      'company_id','company-a',
      'source','github',
      'content','outbox event',
      'record_id','outbox-delivery-1',
      'created_at',now()
    ),
    jsonb_build_object(
      'id','*',
      'record_id','outbox-delivery-1',
      'source','github',
      'event_type','push',
      'content','outbox event',
      'company_id','company-a',
      'payload','{}'::jsonb,
      'created_at',now()
    )
  );
  duplicate_outbox_id := public.persist_ingestion_with_outbox(
    jsonb_build_object(
      'id','70000000-0000-0000-0000-000000000004',
      'company_id','company-a',
      'source','github',
      'event_type','push',
      'payload','{}'::jsonb,
      'delivery_id','outbox-delivery-1',
      'created_at',now()
    ),
    jsonb_build_object(
      'id','71000000-0000-0000-0000-000000000004',
      'company_id','company-a',
      'source','github',
      'content','outbox event',
      'record_id','outbox-delivery-1',
      'created_at',now()
    ),
    jsonb_build_object(
      'id','*',
      'record_id','outbox-delivery-1',
      'source','github',
      'event_type','push',
      'content','outbox event',
      'company_id','company-a',
      'payload','{}'::jsonb,
      'created_at',now()
    )
  );
  IF first_outbox_id <> duplicate_outbox_id THEN
    RAISE EXCEPTION 'duplicate delivery created a second outbox identity';
  END IF;
  SELECT count(*) INTO persisted_count FROM public.events WHERE delivery_id='outbox-delivery-1';
  IF persisted_count <> 1 THEN RAISE EXCEPTION 'duplicate delivery persisted % events', persisted_count; END IF;
  SELECT count(*) INTO persisted_count FROM public.raw_data WHERE record_id='outbox-delivery-1';
  IF persisted_count <> 1 THEN RAISE EXCEPTION 'duplicate delivery persisted % raw rows', persisted_count; END IF;
  SELECT id INTO claimed_id
  FROM public.claim_ingestion_outbox('test-dispatcher', 10, 60)
  WHERE delivery_id='outbox-delivery-1';
  IF claimed_id IS NULL THEN RAISE EXCEPTION 'outbox dispatcher failed to claim pending delivery'; END IF;
  success := public.mark_ingestion_outbox_published(claimed_id, 'test-dispatcher');
  IF NOT success THEN RAISE EXCEPTION 'outbox published marker rejected lease owner'; END IF;
END $$;
DO $$
DECLARE
  claimed_id uuid;
  status text;
BEGIN
  PERFORM public.persist_ingestion_with_outbox(
    jsonb_build_object(
      'id','70000000-0000-0000-0000-000000000005',
      'company_id','company-a',
      'source','github',
      'event_type','push',
      'payload','{}'::jsonb,
      'delivery_id','outbox-delivery-retry',
      'created_at',now()
    ),
    jsonb_build_object(
      'id','71000000-0000-0000-0000-000000000005',
      'company_id','company-a',
      'source','github',
      'content','retry event',
      'record_id','outbox-delivery-retry',
      'created_at',now()
    ),
    jsonb_build_object(
      'id','*',
      'record_id','outbox-delivery-retry',
      'source','github',
      'event_type','push',
      'content','retry event',
      'company_id','company-a',
      'payload','{}'::jsonb,
      'created_at',now()
    )
  );
  SELECT id INTO claimed_id
  FROM public.claim_ingestion_outbox('retry-dispatcher', 10, 60)
  WHERE delivery_id='outbox-delivery-retry';
  IF claimed_id IS NULL THEN RAISE EXCEPTION 'retry test could not claim outbox row'; END IF;
  status := public.fail_ingestion_outbox(
    claimed_id, 'retry-dispatcher', 'redis unavailable', 2
  );
  IF status <> 'pending' THEN RAISE EXCEPTION 'first failure status was %, expected pending', status; END IF;
  UPDATE public.ingestion_outbox SET available_at=now() WHERE id=claimed_id;
  SELECT id INTO claimed_id
  FROM public.claim_ingestion_outbox('retry-dispatcher', 10, 60)
  WHERE delivery_id='outbox-delivery-retry';
  IF claimed_id IS NULL THEN RAISE EXCEPTION 'retry test could not reclaim pending outbox row'; END IF;
  status := public.fail_ingestion_outbox(
    claimed_id, 'retry-dispatcher', 'redis still unavailable', 2
  );
  IF status <> 'dead_letter' THEN RAISE EXCEPTION 'exhausted failure status was %, expected dead_letter', status; END IF;
END $$;
DO $$
DECLARE
  rejected boolean := false;
BEGIN
  BEGIN
    PERFORM public.persist_ingestion_with_outbox(
      jsonb_build_object(
        'id','70000000-0000-0000-0000-000000000006',
        'company_id','company-a',
        'source','github',
        'event_type','push',
        'payload','{}'::jsonb,
        'delivery_id','outbox-invalid-identity',
        'created_at',now()
      ),
      jsonb_build_object(
        'id','71000000-0000-0000-0000-000000000006',
        'company_id','company-a',
        'source','github',
        'content','mismatch',
        'record_id','other-delivery',
        'created_at',now()
      ),
      jsonb_build_object(
        'id','*',
        'record_id','outbox-invalid-identity',
        'source','github',
        'event_type','push',
        'content','mismatch',
        'company_id','company-a',
        'payload','{}'::jsonb,
        'created_at',now()
      )
    );
  EXCEPTION WHEN OTHERS THEN
    rejected := true;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'mismatched raw record identity unexpectedly persisted'; END IF;
  IF EXISTS (SELECT 1 FROM public.events WHERE delivery_id='outbox-invalid-identity') THEN
    RAISE EXCEPTION 'failed outbox transaction left an event row';
  END IF;
  IF EXISTS (SELECT 1 FROM public.raw_data WHERE record_id='other-delivery') THEN
    RAISE EXCEPTION 'failed outbox transaction left a raw-data row';
  END IF;
  IF EXISTS (SELECT 1 FROM public.ingestion_outbox WHERE delivery_id='outbox-invalid-identity') THEN
    RAISE EXCEPTION 'failed outbox transaction left an outbox row';
  END IF;
END $$;
RESET ROLE;

SELECT 'tenant RLS integration tests passed' AS result;
