-- KRT-00: enforce company isolation and keep privileged knowledge paths backend-only.
-- Reviewed against the live KMS DB schema on 2026-11-14.
-- Apply only after running schema/tests/tenant_rls.sql on disposable PostgreSQL.
-- This migration intentionally fails closed if historical tenant ownership is ambiguous.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Validate and enforce tenant ownership invariants.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM public.company_members WHERE user_id IS NULL OR company_id IS NULL)
  THEN RAISE EXCEPTION 'company_members contains null user/company ownership'; END IF;
  IF EXISTS (SELECT 1 FROM public.company_integrations WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'company_integrations contains null company_id'; END IF;
  IF EXISTS (SELECT 1 FROM public.company_repos WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'company_repos contains null company_id'; END IF;
  IF EXISTS (SELECT 1 FROM public.repositories WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'repositories contains null company_id'; END IF;
  IF EXISTS (SELECT 1 FROM public.entities WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'entities contains null company_id'; END IF;
  IF EXISTS (SELECT 1 FROM public.edges WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'edges contains null company_id'; END IF;
  IF EXISTS (SELECT 1 FROM public.raw_data WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'raw_data contains null company_id'; END IF;
  IF EXISTS (SELECT 1 FROM public.events WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'events contains null company_id'; END IF;
  IF EXISTS (SELECT 1 FROM public.playbooks WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'playbooks contains null company_id'; END IF;
  IF EXISTS (SELECT 1 FROM public.ramp_plans WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'ramp_plans contains null company_id'; END IF;
  IF EXISTS (SELECT 1 FROM public.ramp_step_progress WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'ramp_step_progress contains null company_id'; END IF;
  IF EXISTS (SELECT 1 FROM public.ramp_step_feedback WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'ramp_step_feedback contains null company_id'; END IF;

  IF EXISTS (
    SELECT 1 FROM public.edges e
    JOIN public.entities s ON s.id=e.source_id
    JOIN public.entities t ON t.id=e.target_id
    WHERE s.company_id IS DISTINCT FROM e.company_id
       OR t.company_id IS DISTINCT FROM e.company_id
  ) THEN RAISE EXCEPTION 'edges contains cross-company endpoints'; END IF;

  IF EXISTS (
    SELECT 1 FROM public.raw_data d
    JOIN public.events e ON e.id=d.event_id
    WHERE d.event_id IS NOT NULL
      AND d.company_id IS DISTINCT FROM e.company_id
  ) THEN RAISE EXCEPTION 'raw_data/event company ownership mismatch'; END IF;

  IF EXISTS (
    SELECT 1 FROM public.ramp_step_progress p
    JOIN public.ramp_plans r ON r.id=p.plan_id
    WHERE p.company_id IS DISTINCT FROM r.company_id
  ) THEN RAISE EXCEPTION 'ramp_step_progress contains a cross-company plan reference'; END IF;

  IF EXISTS (
    SELECT 1 FROM public.ramp_step_feedback f
    JOIN public.ramp_plans r ON r.id=f.plan_id
    WHERE f.company_id IS DISTINCT FROM r.company_id
  ) THEN RAISE EXCEPTION 'ramp_step_feedback contains a cross-company plan reference'; END IF;
END $$;

DO $
DECLARE
  item record;
  has_invalid_rows boolean;
BEGIN
  IF EXISTS (
    SELECT 1 FROM public.companies
    WHERE id IS NULL OR btrim(id)='' OR lower(btrim(id))='default'
  ) THEN
    RAISE EXCEPTION 'companies contains null, blank, or default identifiers';
  END IF;

  FOR item IN
    SELECT * FROM (VALUES
      ('company_members'),('company_integrations'),('company_repos'),
      ('repositories'),('entities'),('edges'),('raw_data'),('events'),
      ('contributions'),('playbooks'),('ramp_plans'),
      ('ramp_step_progress'),('ramp_step_feedback')
    ) AS tenant_table(table_name)
  LOOP
    EXECUTE format(
      'SELECT EXISTS (SELECT 1 FROM public.%I WHERE company_id IS NULL OR btrim(company_id)='''' OR lower(btrim(company_id))=''default'')',
      item.table_name
    ) INTO has_invalid_rows;
    IF has_invalid_rows THEN
      RAISE EXCEPTION 'public.% contains null, blank, or default company identifiers', item.table_name;
    END IF;
  END LOOP;
END $;

ALTER TABLE public.companies ALTER COLUMN id DROP DEFAULT;

-- Contributions are empty in the audited live DB. If rows appear before this
-- migration is deployed, only an exact repository-to-company match is accepted.
ALTER TABLE public.contributions ADD COLUMN IF NOT EXISTS company_id text;

UPDATE public.contributions c
SET company_id = r.company_id
FROM public.repositories r
WHERE c.company_id IS NULL
  AND c.repo_name = r.full_name;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM public.contributions WHERE company_id IS NULL)
  THEN RAISE EXCEPTION 'contributions contains rows without an unambiguous company; reconcile manually'; END IF;
  IF EXISTS (
    SELECT 1 FROM public.contributions c
    LEFT JOIN public.repositories r
      ON r.full_name=c.repo_name AND r.company_id=c.company_id
    WHERE r.id IS NULL
  ) THEN RAISE EXCEPTION 'contributions company does not match repository ownership'; END IF;
END $$;

ALTER TABLE public.company_members ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE public.company_members ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.company_integrations ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.company_repos ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.repositories ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.entities ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.edges ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.raw_data ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.events ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.contributions ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.playbooks ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.ramp_plans ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.ramp_step_progress ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.ramp_step_feedback ALTER COLUMN company_id SET NOT NULL;

-- Add missing company foreign keys without replacing existing equivalent constraints.
DO $$
DECLARE
  item record;
BEGIN
  FOR item IN
    SELECT * FROM (VALUES
      ('repositories','repositories_company_id_fkey'),
      ('entities','entities_company_id_fkey'),
      ('edges','edges_company_id_fkey'),
      ('raw_data','raw_data_company_id_fkey'),
      ('events','events_company_id_fkey'),
      ('contributions','contributions_company_id_fkey'),
      ('playbooks','playbooks_company_id_fkey'),
      ('ramp_plans','ramp_plans_company_id_fkey'),
      ('ramp_step_progress','ramp_step_progress_company_id_fkey'),
      ('ramp_step_feedback','ramp_step_feedback_company_id_fkey')
    ) AS v(table_name,constraint_name)
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint c
      WHERE c.conrelid = format('public.%I', item.table_name)::regclass
        AND c.contype='f'
        AND c.confrelid='public.companies'::regclass
        AND c.conkey = ARRAY[
          (SELECT attnum FROM pg_attribute
           WHERE attrelid=format('public.%I',item.table_name)::regclass
             AND attname='company_id' AND NOT attisdropped)
        ]::smallint[]
    ) THEN
      EXECUTE format(
        'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE NOT VALID',
        item.table_name, item.constraint_name
      );
    END IF;
  END LOOP;
END $$;

ALTER TABLE public.repositories VALIDATE CONSTRAINT repositories_company_id_fkey;
ALTER TABLE public.entities VALIDATE CONSTRAINT entities_company_id_fkey;
ALTER TABLE public.edges VALIDATE CONSTRAINT edges_company_id_fkey;
ALTER TABLE public.raw_data VALIDATE CONSTRAINT raw_data_company_id_fkey;
ALTER TABLE public.events VALIDATE CONSTRAINT events_company_id_fkey;
ALTER TABLE public.contributions VALIDATE CONSTRAINT contributions_company_id_fkey;
ALTER TABLE public.playbooks VALIDATE CONSTRAINT playbooks_company_id_fkey;
ALTER TABLE public.ramp_plans VALIDATE CONSTRAINT ramp_plans_company_id_fkey;
ALTER TABLE public.ramp_step_progress VALIDATE CONSTRAINT ramp_step_progress_company_id_fkey;
ALTER TABLE public.ramp_step_feedback VALIDATE CONSTRAINT ramp_step_feedback_company_id_fkey;

-- Enforce company equality at relationship boundaries, not only in application code.
DO $
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.entities'::regclass AND conname='entities_id_company_id_key') THEN
    ALTER TABLE public.entities ADD CONSTRAINT entities_id_company_id_key UNIQUE (id,company_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.ramp_plans'::regclass AND conname='ramp_plans_id_company_id_key') THEN
    ALTER TABLE public.ramp_plans ADD CONSTRAINT ramp_plans_id_company_id_key UNIQUE (id,company_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.edges'::regclass AND conname='edges_source_company_fkey') THEN
    ALTER TABLE public.edges ADD CONSTRAINT edges_source_company_fkey
      FOREIGN KEY (source_id,company_id) REFERENCES public.entities(id,company_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.edges'::regclass AND conname='edges_target_company_fkey') THEN
    ALTER TABLE public.edges ADD CONSTRAINT edges_target_company_fkey
      FOREIGN KEY (target_id,company_id) REFERENCES public.entities(id,company_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.raw_data'::regclass AND conname='raw_data_event_company_fkey') THEN
    ALTER TABLE public.raw_data ADD CONSTRAINT raw_data_event_company_fkey
      FOREIGN KEY (event_id,company_id) REFERENCES public.events(id,company_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.ramp_step_progress'::regclass AND conname='ramp_step_progress_plan_company_fkey') THEN
    ALTER TABLE public.ramp_step_progress ADD CONSTRAINT ramp_step_progress_plan_company_fkey
      FOREIGN KEY (plan_id,company_id) REFERENCES public.ramp_plans(id,company_id) ON DELETE CASCADE NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.ramp_step_feedback'::regclass AND conname='ramp_step_feedback_plan_company_fkey') THEN
    ALTER TABLE public.ramp_step_feedback ADD CONSTRAINT ramp_step_feedback_plan_company_fkey
      FOREIGN KEY (plan_id,company_id) REFERENCES public.ramp_plans(id,company_id) ON DELETE CASCADE NOT VALID;
  END IF;
END $;

ALTER TABLE public.edges VALIDATE CONSTRAINT edges_source_company_fkey;
ALTER TABLE public.edges VALIDATE CONSTRAINT edges_target_company_fkey;
ALTER TABLE public.raw_data VALIDATE CONSTRAINT raw_data_event_company_fkey;
ALTER TABLE public.ramp_step_progress VALIDATE CONSTRAINT ramp_step_progress_plan_company_fkey;
ALTER TABLE public.ramp_step_feedback VALIDATE CONSTRAINT ramp_step_feedback_plan_company_fkey;

ALTER TABLE public.contributions DROP CONSTRAINT IF EXISTS contributions_person_name_repo_name_key;
DO $
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid='public.contributions'::regclass
      AND contype='u'
      AND pg_get_constraintdef(oid)='UNIQUE (company_id, person_name, repo_name)'
  ) THEN
    ALTER TABLE public.contributions
      ADD CONSTRAINT contributions_company_person_repo_key
      UNIQUE (company_id,person_name,repo_name);
  END IF;
END $;
CREATE INDEX IF NOT EXISTS idx_contributions_company_repo
  ON public.contributions(company_id, repo_name);

-- Reject blank/default tenant identifiers even when writes bypass RLS.
DO $
DECLARE
  item record;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.companies'::regclass AND conname='companies_id_not_default') THEN
    ALTER TABLE public.companies ADD CONSTRAINT companies_id_not_default
      CHECK (btrim(id)<>'' AND lower(btrim(id))<>'default') NOT VALID;
  END IF;

  FOR item IN
    SELECT * FROM (VALUES
      ('company_members'),('company_integrations'),('company_repos'),
      ('repositories'),('entities'),('edges'),('raw_data'),('events'),
      ('contributions'),('playbooks'),('ramp_plans'),
      ('ramp_step_progress'),('ramp_step_feedback')
    ) AS tenant_table(table_name)
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid=format('public.%I',item.table_name)::regclass
        AND conname=item.table_name||'_company_id_not_default'
    ) THEN
      EXECUTE format(
        'ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (company_id IS NOT NULL AND btrim(company_id)<>'''' AND lower(btrim(company_id))<>''default'') NOT VALID',
        item.table_name,item.table_name||'_company_id_not_default'
      );
    END IF;
  END LOOP;
END $;

ALTER TABLE public.companies VALIDATE CONSTRAINT companies_id_not_default;
ALTER TABLE public.company_members VALIDATE CONSTRAINT company_members_company_id_not_default;
ALTER TABLE public.company_integrations VALIDATE CONSTRAINT company_integrations_company_id_not_default;
ALTER TABLE public.company_repos VALIDATE CONSTRAINT company_repos_company_id_not_default;
ALTER TABLE public.repositories VALIDATE CONSTRAINT repositories_company_id_not_default;
ALTER TABLE public.entities VALIDATE CONSTRAINT entities_company_id_not_default;
ALTER TABLE public.edges VALIDATE CONSTRAINT edges_company_id_not_default;
ALTER TABLE public.raw_data VALIDATE CONSTRAINT raw_data_company_id_not_default;
ALTER TABLE public.events VALIDATE CONSTRAINT events_company_id_not_default;
ALTER TABLE public.contributions VALIDATE CONSTRAINT contributions_company_id_not_default;
ALTER TABLE public.playbooks VALIDATE CONSTRAINT playbooks_company_id_not_default;
ALTER TABLE public.ramp_plans VALIDATE CONSTRAINT ramp_plans_company_id_not_default;
ALTER TABLE public.ramp_step_progress VALIDATE CONSTRAINT ramp_step_progress_company_id_not_default;
ALTER TABLE public.ramp_step_feedback VALIDATE CONSTRAINT ramp_step_feedback_company_id_not_default;

-- ---------------------------------------------------------------------------
-- 2. Non-recursive membership predicate and safe company creation RPC.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.is_company_member(
  p_company_id text,
  p_roles text[] DEFAULT NULL
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.company_members cm
    WHERE cm.user_id = auth.uid()
      AND cm.company_id = p_company_id
      AND (p_roles IS NULL OR cm.role = ANY(p_roles))
  );
$$;

REVOKE ALL ON FUNCTION public.is_company_member(text,text[]) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_company_member(text,text[]) TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public.create_company_with_owner(
  p_company_id text,
  p_name text
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE creator_id uuid := auth.uid();
BEGIN
  IF creator_id IS NULL THEN
    RAISE EXCEPTION 'authenticated user is required' USING ERRCODE='42501';
  END IF;
  IF p_company_id IS NULL OR btrim(p_company_id)='' OR lower(btrim(p_company_id))='default' THEN
    RAISE EXCEPTION 'a real company id is required' USING ERRCODE='22023';
  END IF;
  IF p_name IS NULL OR btrim(p_name)='' THEN
    RAISE EXCEPTION 'company name is required' USING ERRCODE='22023';
  END IF;

  INSERT INTO public.companies(id,name) VALUES (btrim(p_company_id),btrim(p_name));
  INSERT INTO public.company_members(user_id,company_id,role,is_owner)
  VALUES (creator_id,btrim(p_company_id),'admin',true);
  RETURN btrim(p_company_id);
END;
$$;

REVOKE ALL ON FUNCTION public.create_company_with_owner(text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.create_company_with_owner(text,text) TO authenticated;

-- ---------------------------------------------------------------------------
-- 3. Replace permissive policies and enable RLS on all public tenant tables.
-- ---------------------------------------------------------------------------

DO $$
DECLARE p record;
BEGIN
  FOR p IN
    SELECT schemaname,tablename,policyname
    FROM pg_policies
    WHERE schemaname='public'
      AND tablename = ANY(ARRAY[
        'companies','company_members','company_integrations','company_repos',
        'repositories','codebase_files','codebase_modules','file_entity_links',
        'entities','edges','raw_data','playbooks','ramp_plans','ramp_step_progress',
        'events','contributions','pull_requests','issues','query_logs',
        'ingestion_outbox','ramp_step_feedback'
      ])
  LOOP
    EXECUTE format('DROP POLICY %I ON %I.%I',p.policyname,p.schemaname,p.tablename);
  END LOOP;
END $$;

ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_repos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.repositories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.codebase_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.codebase_modules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.file_entity_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.raw_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.playbooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ramp_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ramp_step_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contributions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pull_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.query_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ingestion_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ramp_step_feedback ENABLE ROW LEVEL SECURITY;

-- Membership: users cannot enroll themselves, self-promote, or remove themselves.
CREATE POLICY company_members_read_authorized
ON public.company_members FOR SELECT TO authenticated
USING (
  user_id=auth.uid()
  OR public.is_company_member(company_id,ARRAY['admin','manager'])
);

CREATE POLICY company_admins_update_members
ON public.company_members FOR UPDATE TO authenticated
USING (
  user_id<>auth.uid()
  AND NOT COALESCE(is_owner,false)
  AND public.is_company_member(company_id,ARRAY['admin'])
)
WITH CHECK (
  user_id<>auth.uid()
  AND NOT COALESCE(is_owner,false)
  AND role IN ('admin','manager','member')
  AND public.is_company_member(company_id,ARRAY['admin'])
);

CREATE POLICY company_admins_delete_members
ON public.company_members FOR DELETE TO authenticated
USING (
  user_id<>auth.uid()
  AND NOT COALESCE(is_owner,false)
  AND public.is_company_member(company_id,ARRAY['admin'])
);

CREATE POLICY companies_member_read
ON public.companies FOR SELECT TO authenticated
USING (public.is_company_member(id));

CREATE POLICY company_repos_member_read
ON public.company_repos FOR SELECT TO authenticated
USING (public.is_company_member(company_id));

CREATE POLICY company_repos_admin_manage
ON public.company_repos FOR ALL TO authenticated
USING (public.is_company_member(company_id,ARRAY['admin']))
WITH CHECK (public.is_company_member(company_id,ARRAY['admin']));

CREATE POLICY repositories_member_read
ON public.repositories FOR SELECT TO authenticated
USING (public.is_company_member(company_id));

CREATE POLICY codebase_files_member_read
ON public.codebase_files FOR SELECT TO authenticated
USING (EXISTS (
  SELECT 1 FROM public.repositories r
  WHERE r.id=codebase_files.repository_id
    AND public.is_company_member(r.company_id)
));

CREATE POLICY codebase_modules_member_read
ON public.codebase_modules FOR SELECT TO authenticated
USING (EXISTS (
  SELECT 1 FROM public.repositories r
  WHERE r.id=codebase_modules.repository_id
    AND public.is_company_member(r.company_id)
));

CREATE POLICY file_entity_links_member_read
ON public.file_entity_links FOR SELECT TO authenticated
USING (EXISTS (
  SELECT 1
  FROM public.codebase_files f
  JOIN public.repositories r ON r.id=f.repository_id
  JOIN public.entities e ON e.id=file_entity_links.entity_id
  WHERE f.id=file_entity_links.file_id
    AND e.company_id=r.company_id
    AND public.is_company_member(r.company_id)
));

CREATE POLICY entities_member_read
ON public.entities FOR SELECT TO authenticated
USING (public.is_company_member(company_id));

CREATE POLICY edges_member_read
ON public.edges FOR SELECT TO authenticated
USING (
  public.is_company_member(company_id)
  AND EXISTS (
    SELECT 1 FROM public.entities s
    JOIN public.entities t ON t.id=edges.target_id
    WHERE s.id=edges.source_id
      AND s.company_id=edges.company_id
      AND t.company_id=edges.company_id
  )
);

CREATE POLICY playbooks_member_read
ON public.playbooks FOR SELECT TO authenticated
USING (public.is_company_member(company_id));

CREATE POLICY ramp_plans_member_read
ON public.ramp_plans FOR SELECT TO authenticated
USING (public.is_company_member(company_id));

CREATE POLICY ramp_step_progress_member_read
ON public.ramp_step_progress FOR SELECT TO authenticated
USING (
  public.is_company_member(company_id)
  AND (user_id=auth.uid()::text OR public.is_company_member(company_id,ARRAY['admin']))
);

-- Profiles do not carry company_id; visibility follows shared membership.
DROP POLICY IF EXISTS "Users can view own profile" ON public.profiles;
CREATE POLICY profiles_self_or_company_member_read
ON public.profiles FOR SELECT TO authenticated
USING (
  id=auth.uid()
  OR EXISTS (
    SELECT 1 FROM public.company_members cm
    WHERE cm.user_id=profiles.id
      AND public.is_company_member(cm.company_id)
  )
);

-- ---------------------------------------------------------------------------
-- 4. Remove browser access to secrets, raw events, analytics and worker queues.
-- ---------------------------------------------------------------------------

REVOKE ALL ON TABLE
  public.companies, public.company_members, public.company_integrations,
  public.company_repos, public.repositories, public.codebase_files,
  public.codebase_modules, public.file_entity_links, public.entities,
  public.edges, public.raw_data, public.playbooks, public.ramp_plans,
  public.ramp_step_progress, public.events, public.contributions,
  public.pull_requests, public.issues, public.query_logs,
  public.ingestion_outbox, public.ramp_step_feedback, public.profiles
FROM PUBLIC, anon, authenticated;

GRANT SELECT ON TABLE
  public.companies, public.company_members, public.company_repos,
  public.repositories, public.codebase_files, public.codebase_modules,
  public.file_entity_links, public.entities, public.edges,
  public.playbooks, public.ramp_plans, public.ramp_step_progress,
  public.profiles
TO authenticated;

GRANT UPDATE ON TABLE public.company_members TO authenticated;
GRANT ALL ON TABLE
  public.companies, public.company_members, public.company_integrations,
  public.company_repos, public.repositories, public.codebase_files,
  public.codebase_modules, public.file_entity_links, public.entities,
  public.edges, public.raw_data, public.playbooks, public.ramp_plans,
  public.ramp_step_progress, public.events, public.contributions,
  public.pull_requests, public.issues, public.query_logs,
  public.ingestion_outbox, public.ramp_step_feedback
TO service_role;

-- ---------------------------------------------------------------------------
-- 5. Tenant-required RPCs and least-privilege execution grants.
-- ---------------------------------------------------------------------------

-- pgvector is installed in the live Supabase project under the extensions schema.
-- Keep the migration runnable on disposable PostgreSQL instances that do not ship
-- pgvector; those environments still exercise all non-vector RLS/RPC assertions.
DO $$
BEGIN
  IF to_regtype('extensions.vector') IS NOT NULL THEN
    EXECUTE $vector_fn$
      CREATE OR REPLACE FUNCTION public.match_documents(
        query_embedding extensions.vector,
        match_threshold double precision,
        match_count integer,
        filter_company_id text
      )
      RETURNS TABLE (
        id uuid, record_id text, content text, source text,
        created_at timestamptz, company_id text, similarity double precision
      )
      LANGUAGE plpgsql
      SECURITY INVOKER
      SET search_path = pg_catalog, public, extensions
      AS $body$
      BEGIN
        IF filter_company_id IS NULL OR btrim(filter_company_id)=''
           OR lower(btrim(filter_company_id))='default' THEN
          RAISE EXCEPTION 'a real filter_company_id is required' USING ERRCODE='22023';
        END IF;
        IF match_count IS NULL OR match_count<1 OR match_count>100
           OR match_threshold IS NULL OR match_threshold<0 OR match_threshold>1 THEN
          RAISE EXCEPTION 'invalid vector search bounds' USING ERRCODE='22023';
        END IF;

        RETURN QUERY
        SELECT r.id,r.record_id,r.content,r.source,r.created_at,r.company_id,
          (1-(r.embedding <=> query_embedding))::double precision
        FROM public.raw_data r
        WHERE r.company_id=filter_company_id
          AND r.embedding IS NOT NULL
          AND (r.embedding <=> query_embedding)<(1-match_threshold)
        ORDER BY r.embedding <=> query_embedding
        LIMIT match_count;
      END;
      $body$;
    $vector_fn$;

    EXECUTE 'REVOKE ALL ON FUNCTION public.match_documents(extensions.vector,double precision,integer,text) FROM PUBLIC, anon, authenticated';
    EXECUTE 'GRANT EXECUTE ON FUNCTION public.match_documents(extensions.vector,double precision,integer,text) TO service_role';
  ELSE
    RAISE NOTICE 'pgvector extension not installed; match_documents hardening skipped in this disposable database';
  END IF;
END $$;

DROP FUNCTION IF EXISTS public.search_edges_by_entity(text,text[]);

CREATE OR REPLACE FUNCTION public.search_edges_by_entity(
  search_term text,
  relation_types text[],
  filter_company_id text
)
RETURNS TABLE (
  id uuid, source_name text, target_name text,
  type text, confidence double precision
)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF filter_company_id IS NULL OR btrim(filter_company_id)=''
     OR lower(btrim(filter_company_id))='default' THEN
    RAISE EXCEPTION 'a real filter_company_id is required' USING ERRCODE='22023';
  END IF;
  IF search_term IS NULL OR btrim(search_term)='' THEN
    RETURN;
  END IF;

  RETURN QUERY
  SELECT e.id,s.name,t.name,e.type,
    COALESCE((e.metadata->>'confidence')::double precision,e.confidence,0.9)
  FROM public.edges e
  JOIN public.entities s ON s.id=e.source_id AND s.company_id=filter_company_id
  JOIN public.entities t ON t.id=e.target_id AND t.company_id=filter_company_id
  WHERE e.company_id=filter_company_id
    AND (
      lower(s.name) LIKE '%'||lower(search_term)||'%'
      OR lower(t.name) LIKE '%'||lower(search_term)||'%'
    )
    AND (COALESCE(cardinality(relation_types),0)=0 OR e.type=ANY(relation_types))
  ORDER BY COALESCE((e.metadata->>'confidence')::double precision,e.confidence,0.9) DESC
  LIMIT 10;
END;
$$;

REVOKE ALL ON FUNCTION public.search_edges_by_entity(text,text[],text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.search_edges_by_entity(text,text[],text)
  TO service_role;

CREATE OR REPLACE FUNCTION public.reconcile_repository_files(
  p_repository_id uuid,
  p_company_id text,
  p_live_paths text[]
)
RETURNS void
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_repository_id IS NULL OR p_company_id IS NULL
     OR btrim(p_company_id)='' OR lower(btrim(p_company_id))='default'
     OR p_live_paths IS NULL THEN
    RAISE EXCEPTION 'repository_id, valid company_id, and complete live_paths are required';
  END IF;
  IF EXISTS (
    SELECT 1 FROM unnest(p_live_paths) p(path)
    WHERE p.path IS NULL OR btrim(p.path)=''
  ) THEN
    RAISE EXCEPTION 'live_paths cannot contain null or blank paths';
  END IF;
  IF cardinality(p_live_paths)<>(SELECT count(DISTINCT path) FROM unnest(p_live_paths) p(path)) THEN
    RAISE EXCEPTION 'live_paths must be unique';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.repositories r
    WHERE r.id=p_repository_id AND r.company_id=p_company_id
  ) THEN
    RAISE EXCEPTION 'repository does not belong to requested company' USING ERRCODE='42501';
  END IF;

  DELETE FROM public.codebase_files
  WHERE repository_id=p_repository_id
    AND NOT (file_path=ANY(p_live_paths));
END;
$$;

REVOKE ALL ON FUNCTION public.reconcile_repository_files(uuid,text,text[])
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reconcile_repository_files(uuid,text,text[])
  TO service_role;

ALTER FUNCTION public.replace_implementation_edges(text,uuid[],jsonb)
  SET search_path = pg_catalog, public;
REVOKE ALL ON FUNCTION public.replace_implementation_edges(text,uuid[],jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.replace_implementation_edges(text,uuid[],jsonb)
  TO service_role;

COMMIT;
