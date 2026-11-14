-- Company isolation policies and service-role boundary.
-- Apply only after 20261031_tenant_guardrails.sql succeeds.
-- No existing application data is changed by this migration.

BEGIN;

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

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
    FROM public.company_members AS cm
    WHERE cm.user_id = auth.uid()
      AND cm.company_id = p_company_id
      AND (p_roles IS NULL OR cm.role = ANY (p_roles))
  );
$$;

REVOKE ALL ON FUNCTION public.is_company_member(text, text[]) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_company_member(text, text[]) TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public.create_company_with_owner(
  p_company_id text,
  p_name text
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  creator_id uuid := auth.uid();
BEGIN
  IF creator_id IS NULL THEN
    RAISE EXCEPTION 'authenticated user is required' USING ERRCODE = '42501';
  END IF;
  IF p_company_id IS NULL OR btrim(p_company_id) = ''
     OR lower(btrim(p_company_id)) = 'default' THEN
    RAISE EXCEPTION 'a real company id is required' USING ERRCODE = '22023';
  END IF;
  IF p_name IS NULL OR btrim(p_name) = '' THEN
    RAISE EXCEPTION 'company name is required' USING ERRCODE = '22023';
  END IF;

  INSERT INTO public.companies (id, name)
  VALUES (btrim(p_company_id), btrim(p_name));

  INSERT INTO public.company_members (user_id, company_id, role, is_owner)
  VALUES (creator_id, btrim(p_company_id), 'admin', true);

  RETURN btrim(p_company_id);
END;
$$;

REVOKE ALL ON FUNCTION public.create_company_with_owner(text, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.create_company_with_owner(text, text) TO authenticated;

DO $$
DECLARE
  policy_row record;
  table_name text;
  protected_tables text[] := ARRAY[
    'companies',
    'company_members',
    'company_integrations',
    'company_repos',
    'repositories',
    'codebase_files',
    'codebase_modules',
    'file_entity_links',
    'entities',
    'edges',
    'raw_data',
    'playbooks',
    'ramp_plans',
    'ramp_step_progress',
    'events',
    'contributions',
    'pull_requests',
    'issues',
    'query_logs'
  ];
BEGIN
  FOR policy_row IN
    SELECT schemaname, tablename, policyname
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = ANY (protected_tables)
  LOOP
    EXECUTE format(
      'DROP POLICY %I ON %I.%I',
      policy_row.policyname,
      policy_row.schemaname,
      policy_row.tablename
    );
  END LOOP;

  FOREACH table_name IN ARRAY protected_tables LOOP
    IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    END IF;
  END LOOP;
END $$;

-- Membership policies call a SECURITY DEFINER predicate so they never query
-- company_members through its own RLS policy (which would recurse).
CREATE POLICY "company members read authorized memberships"
ON public.company_members
FOR SELECT TO authenticated
USING (
  user_id = auth.uid()
  OR public.is_company_member(company_id, ARRAY['admin', 'manager'])
);

CREATE POLICY "company admins and managers invite members"
ON public.company_members
FOR INSERT TO authenticated
WITH CHECK (
  user_id <> auth.uid()
  AND NOT COALESCE(is_owner, false)
  AND (
    public.is_company_member(company_id, ARRAY['admin'])
    OR (
      role = 'member'
      AND public.is_company_member(company_id, ARRAY['manager'])
    )
  )
);

CREATE POLICY "company admins update non-owner memberships"
ON public.company_members
FOR UPDATE TO authenticated
USING (
  user_id <> auth.uid()
  AND NOT COALESCE(is_owner, false)
  AND public.is_company_member(company_id, ARRAY['admin'])
)
WITH CHECK (
  user_id <> auth.uid()
  AND NOT COALESCE(is_owner, false)
  AND role IN ('admin', 'manager', 'member')
  AND public.is_company_member(company_id, ARRAY['admin'])
);

CREATE POLICY "company admins remove non-owner memberships"
ON public.company_members
FOR DELETE TO authenticated
USING (
  user_id <> auth.uid()
  AND NOT COALESCE(is_owner, false)
  AND public.is_company_member(company_id, ARRAY['admin'])
);

CREATE POLICY "members read companies"
ON public.companies
FOR SELECT TO authenticated
USING (public.is_company_member(id));

CREATE POLICY "company repositories are member-readable"
ON public.company_repos
FOR SELECT TO authenticated
USING (public.is_company_member(company_id));

CREATE POLICY "company admins manage company repositories"
ON public.company_repos
FOR ALL TO authenticated
USING (public.is_company_member(company_id, ARRAY['admin']))
WITH CHECK (public.assert_real_company(company_id)
  AND public.is_company_member(company_id, ARRAY['admin']));

CREATE POLICY "company repositories are member-readable"
ON public.repositories
FOR SELECT TO authenticated
USING (public.is_company_member(company_id));

CREATE POLICY "company codebase files are member-readable"
ON public.codebase_files
FOR SELECT TO authenticated
USING (
  EXISTS (
    SELECT 1 FROM public.repositories AS r
    WHERE r.id = codebase_files.repository_id
      AND public.is_company_member(r.company_id)
  )
);

CREATE POLICY "company codebase modules are member-readable"
ON public.codebase_modules
FOR SELECT TO authenticated
USING (
  EXISTS (
    SELECT 1 FROM public.repositories AS r
    WHERE r.id = codebase_modules.repository_id
      AND public.is_company_member(r.company_id)
  )
);

CREATE POLICY "company file entity links are member-readable"
ON public.file_entity_links
FOR SELECT TO authenticated
USING (
  EXISTS (
    SELECT 1
    FROM public.codebase_files AS f
    JOIN public.repositories AS r ON r.id = f.repository_id
    JOIN public.entities AS e ON e.id = file_entity_links.entity_id
    WHERE f.id = file_entity_links.file_id
      AND e.company_id = r.company_id
      AND public.is_company_member(r.company_id)
  )
);

CREATE POLICY "company entities are member-readable"
ON public.entities
FOR SELECT TO authenticated
USING (public.is_company_member(company_id));

CREATE POLICY "company edges are member-readable"
ON public.edges
FOR SELECT TO authenticated
USING (
  public.is_company_member(company_id)
  AND EXISTS (
    SELECT 1
    FROM public.entities AS source_entity
    JOIN public.entities AS target_entity ON target_entity.id = edges.target_id
    WHERE source_entity.id = edges.source_id
      AND source_entity.company_id = edges.company_id
      AND target_entity.company_id = edges.company_id
  )
);

CREATE POLICY "company raw data is member-readable"
ON public.raw_data
FOR SELECT TO authenticated
USING (public.is_company_member(company_id));

CREATE POLICY "company playbooks are member-readable"
ON public.playbooks
FOR SELECT TO authenticated
USING (public.is_company_member(company_id));

CREATE POLICY "company admins manage playbooks"
ON public.playbooks
FOR ALL TO authenticated
USING (public.is_company_member(company_id, ARRAY['admin']))
WITH CHECK (public.assert_real_company(company_id)
  AND public.is_company_member(company_id, ARRAY['admin']));

CREATE POLICY "members read ramp plans"
ON public.ramp_plans
FOR SELECT TO authenticated
USING (public.is_company_member(company_id));

CREATE POLICY "company admins manage ramp plans"
ON public.ramp_plans
FOR ALL TO authenticated
USING (public.is_company_member(company_id, ARRAY['admin']))
WITH CHECK (public.assert_real_company(company_id)
  AND public.is_company_member(company_id, ARRAY['admin']));

CREATE POLICY "members manage own company ramp progress"
ON public.ramp_step_progress
FOR ALL TO authenticated
USING (
  public.is_company_member(company_id)
  AND (
    user_id = auth.uid()::text
    OR public.is_company_member(company_id, ARRAY['admin'])
  )
)
WITH CHECK (
  public.assert_real_company(company_id)
  AND public.is_company_member(company_id)
  AND (
    user_id = auth.uid()::text
    OR public.is_company_member(company_id, ARRAY['admin'])
  )
);

-- Raw events, analytics, and legacy unscoped datasets are backend-only.
-- RLS is enabled above with no authenticated policies: this is deliberate default-deny.
REVOKE ALL ON TABLE
  public.companies,
  public.company_members,
  public.company_integrations,
  public.company_repos,
  public.repositories,
  public.codebase_files,
  public.codebase_modules,
  public.file_entity_links,
  public.entities,
  public.edges,
  public.raw_data,
  public.playbooks,
  public.ramp_plans,
  public.ramp_step_progress,
  public.events,
  public.contributions,
  public.pull_requests,
  public.issues,
  public.query_logs
FROM anon, authenticated;

GRANT SELECT ON TABLE
  public.companies,
  public.company_members,
  public.company_repos,
  public.repositories,
  public.codebase_files,
  public.codebase_modules,
  public.file_entity_links,
  public.entities,
  public.edges,
  public.raw_data,
  public.playbooks,
  public.ramp_plans,
  public.ramp_step_progress
TO authenticated;

GRANT INSERT, UPDATE, DELETE ON TABLE public.company_members TO authenticated;
GRANT INSERT, UPDATE, DELETE ON TABLE public.company_repos, public.ramp_plans TO authenticated;
GRANT INSERT, UPDATE, DELETE ON TABLE public.ramp_step_progress TO authenticated;
GRANT INSERT, UPDATE, DELETE ON TABLE public.playbooks TO authenticated;

GRANT ALL ON TABLE
  public.companies,
  public.company_members,
  public.company_integrations,
  public.company_repos,
  public.repositories,
  public.codebase_files,
  public.codebase_modules,
  public.file_entity_links,
  public.entities,
  public.edges,
  public.raw_data,
  public.playbooks,
  public.ramp_plans,
  public.ramp_step_progress,
  public.events,
  public.contributions,
  public.pull_requests,
  public.issues,
  public.query_logs
TO service_role;

COMMIT;
