-- Repository snapshots provide an immutable staging area and a single atomic
-- publication point. Existing rows remain legacy rows (snapshot_id IS NULL)
-- until a repository completes its first versioned sync.

BEGIN;

CREATE TABLE IF NOT EXISTS public.repository_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  repository_id uuid NOT NULL REFERENCES public.repositories(id) ON DELETE CASCADE,
  company_id text NOT NULL,
  source_revision text NOT NULL CHECK (btrim(source_revision) <> ''),
  run_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'building'
    CHECK (status IN ('building', 'published', 'superseded', 'failed')),
  file_count integer,
  module_count integer,
  relationship_count integer,
  validation jsonb NOT NULL DEFAULT '{}'::jsonb,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  UNIQUE (repository_id, id),
  UNIQUE (id, company_id)
);

CREATE INDEX IF NOT EXISTS idx_repository_snapshots_repo_created
  ON public.repository_snapshots(repository_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_repository_snapshots_status
  ON public.repository_snapshots(status);

ALTER TABLE public.repositories
  ADD COLUMN IF NOT EXISTS active_snapshot_id uuid;

ALTER TABLE public.repositories
  DROP CONSTRAINT IF EXISTS repositories_active_snapshot_fk;

ALTER TABLE public.repositories
  ADD CONSTRAINT repositories_active_snapshot_fk
  FOREIGN KEY (id, active_snapshot_id)
  REFERENCES public.repository_snapshots(repository_id, id)
  DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE public.codebase_files
  ADD COLUMN IF NOT EXISTS snapshot_id uuid;

ALTER TABLE public.codebase_modules
  ADD COLUMN IF NOT EXISTS snapshot_id uuid;

ALTER TABLE public.edges
  ADD COLUMN IF NOT EXISTS snapshot_id uuid;

-- Keep the pre-snapshot inventory rows unique, while allowing one row per path
-- in each immutable snapshot. Existing rows have NULL snapshot_id and remain
-- readable by legacy consumers during the compatibility period.
ALTER TABLE public.codebase_files
  DROP CONSTRAINT IF EXISTS codebase_files_repository_id_file_path_key;
ALTER TABLE public.codebase_files
  ADD CONSTRAINT codebase_files_repository_path_snapshot_key
  UNIQUE (repository_id, file_path, snapshot_id);

ALTER TABLE public.codebase_modules
  DROP CONSTRAINT IF EXISTS codebase_modules_repository_id_module_path_key;
ALTER TABLE public.codebase_modules
  ADD CONSTRAINT codebase_modules_repository_module_snapshot_key
  UNIQUE (repository_id, module_path, snapshot_id);

-- PostgreSQL treats NULL values as distinct in ordinary unique constraints.
-- Preserve one legacy row per repository/path while snapshots are introduced.
CREATE UNIQUE INDEX IF NOT EXISTS codebase_files_legacy_repository_path_key
  ON public.codebase_files(repository_id, file_path)
  WHERE snapshot_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS codebase_modules_legacy_repository_path_key
  ON public.codebase_modules(repository_id, module_path)
  WHERE snapshot_id IS NULL;

ALTER TABLE public.codebase_files
  DROP CONSTRAINT IF EXISTS codebase_files_snapshot_repository_fk;
ALTER TABLE public.codebase_files
  ADD CONSTRAINT codebase_files_snapshot_repository_fk
  FOREIGN KEY (repository_id, snapshot_id)
  REFERENCES public.repository_snapshots(repository_id, id)
  ON DELETE CASCADE;

ALTER TABLE public.codebase_modules
  DROP CONSTRAINT IF EXISTS codebase_modules_snapshot_repository_fk;
ALTER TABLE public.codebase_modules
  ADD CONSTRAINT codebase_modules_snapshot_repository_fk
  FOREIGN KEY (repository_id, snapshot_id)
  REFERENCES public.repository_snapshots(repository_id, id)
  ON DELETE CASCADE;

ALTER TABLE public.edges
  DROP CONSTRAINT IF EXISTS edges_snapshot_company_fk;
ALTER TABLE public.edges
  ADD CONSTRAINT edges_snapshot_company_fk
  FOREIGN KEY (snapshot_id, company_id)
  REFERENCES public.repository_snapshots(id, company_id)
  ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_codebase_files_snapshot
  ON public.codebase_files(snapshot_id, repository_id, file_path);
CREATE INDEX IF NOT EXISTS idx_codebase_modules_snapshot
  ON public.codebase_modules(snapshot_id, repository_id, module_path);
CREATE INDEX IF NOT EXISTS idx_edges_snapshot_source_type
  ON public.edges(snapshot_id, source_id, type)
  WHERE snapshot_id IS NOT NULL;

ALTER TABLE public.repository_snapshots ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.repository_snapshots FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.repository_snapshots TO service_role;

-- A legacy ready baseline is not considered complete until it has an active
-- immutable snapshot. This forces one clean snapshot build on the first sync
-- after this migration, even when the Git commit has not changed.
CREATE OR REPLACE FUNCTION public.claim_repository_baseline(
  p_full_name text,
  p_company_id text,
  p_source_revision text,
  p_run_id uuid,
  p_lease_seconds integer DEFAULT 180
)
RETURNS text
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $claim$
DECLARE
  repo_row public.repositories%ROWTYPE;
BEGIN
  IF p_full_name IS NULL OR btrim(p_full_name) = ''
     OR p_company_id IS NULL OR btrim(p_company_id) = ''
     OR lower(btrim(p_company_id)) = 'default'
     OR p_source_revision IS NULL OR btrim(p_source_revision) = ''
     OR p_run_id IS NULL OR p_lease_seconds IS NULL
     OR p_lease_seconds < 30 OR p_lease_seconds > 3600 THEN
    RAISE EXCEPTION 'valid repository, company, revision, run id, and lease duration are required';
  END IF;

  SELECT * INTO repo_row
  FROM public.repositories
  WHERE full_name = p_full_name AND company_id = p_company_id
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'repository not found for company';
  END IF;

  IF repo_row.baseline_status = 'ready'
     AND repo_row.baseline_revision = p_source_revision
     AND repo_row.active_snapshot_id IS NOT NULL THEN
    RETURN 'ready';
  END IF;

  IF repo_row.baseline_status = 'indexing'
     AND repo_row.baseline_lease_expires_at > now() THEN
    RETURN 'busy';
  END IF;

  UPDATE public.repositories
  SET baseline_status = 'indexing',
      baseline_run_id = p_run_id,
      baseline_lease_expires_at = now() + make_interval(secs => p_lease_seconds),
      baseline_started_at = now(),
      baseline_error = NULL
  WHERE id = repo_row.id;

  RETURN 'claimed';
END;
$claim$;

REVOKE ALL ON FUNCTION public.claim_repository_baseline(text,text,text,uuid,integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_repository_baseline(text,text,text,uuid,integer)
  TO service_role;

-- The worker may create a staging snapshot only while it owns the live lease.
CREATE OR REPLACE FUNCTION public.create_repository_snapshot(
  p_repository_id uuid,
  p_company_id text,
  p_run_id uuid,
  p_source_revision text,
  p_snapshot_id uuid DEFAULT gen_random_uuid()
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_snapshot_id uuid := COALESCE(p_snapshot_id, gen_random_uuid());
BEGIN
  IF p_repository_id IS NULL OR p_company_id IS NULL
     OR btrim(p_company_id) = '' OR lower(btrim(p_company_id)) = 'default'
     OR p_run_id IS NULL OR p_source_revision IS NULL
     OR btrim(p_source_revision) = '' THEN
    RAISE EXCEPTION 'repository, company, run, and immutable source revision are required'
      USING ERRCODE = '22023';
  END IF;

  PERFORM 1
  FROM public.repositories r
  WHERE r.id = p_repository_id
    AND r.company_id = p_company_id
    AND r.baseline_status = 'indexing'
    AND r.baseline_run_id = p_run_id
    AND r.baseline_lease_expires_at > now()
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'repository baseline lease is not owned by this run'
      USING ERRCODE = '42501';
  END IF;

  INSERT INTO public.repository_snapshots (
    id, repository_id, company_id, source_revision, run_id, status
  ) VALUES (
    v_snapshot_id, p_repository_id, p_company_id, p_source_revision, p_run_id, 'building'
  );

  RETURN v_snapshot_id;
END;
$$;

-- Publish is deliberately short: the expensive GitHub traversal and extraction
-- happen before this transaction. Counts are checked against staged rows before
-- the active pointer is changed.
CREATE OR REPLACE FUNCTION public.publish_repository_snapshot(
  p_snapshot_id uuid,
  p_run_id uuid,
  p_file_count integer,
  p_module_count integer,
  p_relationship_count integer,
  p_completed_at timestamptz DEFAULT now()
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_snapshot public.repository_snapshots%ROWTYPE;
  v_repository public.repositories%ROWTYPE;
  v_actual_files integer;
  v_actual_modules integer;
  v_actual_relationships integer;
BEGIN
  IF p_snapshot_id IS NULL OR p_run_id IS NULL
     OR p_file_count IS NULL OR p_file_count < 0
     OR p_module_count IS NULL OR p_module_count < 0
     OR p_relationship_count IS NULL OR p_relationship_count < 0
     OR p_completed_at IS NULL THEN
    RAISE EXCEPTION 'snapshot, run, non-negative counts, and completion timestamp are required'
      USING ERRCODE = '22023';
  END IF;

  SELECT * INTO v_snapshot
  FROM public.repository_snapshots
  WHERE id = p_snapshot_id
  FOR UPDATE;

  IF NOT FOUND OR v_snapshot.run_id <> p_run_id OR v_snapshot.status <> 'building' THEN
    RETURN false;
  END IF;

  SELECT * INTO v_repository
  FROM public.repositories
  WHERE id = v_snapshot.repository_id
    AND company_id = v_snapshot.company_id
  FOR UPDATE;

  IF NOT FOUND OR v_repository.baseline_status <> 'indexing'
     OR v_repository.baseline_run_id <> p_run_id
     OR v_repository.baseline_lease_expires_at <= now() THEN
    RETURN false;
  END IF;

  SELECT count(*) INTO v_actual_files
  FROM public.codebase_files
  WHERE repository_id = v_snapshot.repository_id
    AND snapshot_id = p_snapshot_id;

  SELECT count(*) INTO v_actual_modules
  FROM public.codebase_modules
  WHERE repository_id = v_snapshot.repository_id
    AND snapshot_id = p_snapshot_id;

  SELECT count(*) INTO v_actual_relationships
  FROM public.edges
  WHERE snapshot_id = p_snapshot_id
    AND company_id = v_snapshot.company_id
    AND type IN ('IMPORTS', 'ROUTE_HANDLER_OPERATION');

  IF v_actual_files <> p_file_count
     OR v_actual_modules <> p_module_count
     OR v_actual_relationships <> p_relationship_count THEN
    RAISE EXCEPTION
      'snapshot validation count mismatch (files %, modules %, relationships %; expected %, %, %)',
      v_actual_files, v_actual_modules, v_actual_relationships,
      p_file_count, p_module_count, p_relationship_count
      USING ERRCODE = '23514';
  END IF;

  IF v_repository.active_snapshot_id IS NOT NULL THEN
    UPDATE public.repository_snapshots
    SET status = 'superseded'
    WHERE id = v_repository.active_snapshot_id
      AND repository_id = v_snapshot.repository_id
      AND status = 'published';
  END IF;

  UPDATE public.repository_snapshots
  SET status = 'published',
      file_count = p_file_count,
      module_count = p_module_count,
      relationship_count = p_relationship_count,
      completed_at = p_completed_at,
      error = NULL
  WHERE id = p_snapshot_id;

  UPDATE public.repositories
  SET active_snapshot_id = p_snapshot_id,
      baseline_status = 'ready',
      baseline_revision = v_snapshot.source_revision,
      baseline_file_count = p_file_count,
      baseline_completed_at = p_completed_at,
      baseline_error = NULL,
      baseline_run_id = NULL,
      baseline_lease_expires_at = NULL,
      last_synced_at = p_completed_at,
      updated_at = p_completed_at
  WHERE id = v_snapshot.repository_id
    AND company_id = v_snapshot.company_id;

  RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_repository_snapshot(
  p_snapshot_id uuid,
  p_run_id uuid,
  p_error text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_snapshot public.repository_snapshots%ROWTYPE;
  v_affected integer;
BEGIN
  IF p_snapshot_id IS NULL OR p_run_id IS NULL THEN
    RAISE EXCEPTION 'snapshot_id and run_id are required' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO v_snapshot
  FROM public.repository_snapshots
  WHERE id = p_snapshot_id AND run_id = p_run_id
  FOR UPDATE;

  IF NOT FOUND OR v_snapshot.status <> 'building' THEN
    RETURN false;
  END IF;

  UPDATE public.repository_snapshots
  SET status = 'failed',
      error = COALESCE(NULLIF(left(p_error, 2000), ''), 'Snapshot indexing failed'),
      completed_at = now()
  WHERE id = p_snapshot_id AND run_id = p_run_id;

  UPDATE public.repositories
  SET baseline_status = CASE WHEN active_snapshot_id IS NULL THEN 'failed' ELSE 'ready' END,
      baseline_error = COALESCE(NULLIF(left(p_error, 2000), ''), 'Snapshot indexing failed'),
      baseline_run_id = NULL,
      baseline_lease_expires_at = NULL,
      updated_at = now()
  WHERE id = v_snapshot.repository_id
    AND company_id = v_snapshot.company_id
    AND baseline_status = 'indexing'
    AND baseline_run_id = p_run_id;

  GET DIAGNOSTICS v_affected = ROW_COUNT;
  RETURN v_affected = 1;
END;
$$;

-- Replace implementation edges inside one unpublished snapshot. The previous
-- published snapshot is untouched, including edges for the same source files.
CREATE OR REPLACE FUNCTION public.replace_snapshot_implementation_edges(
  p_snapshot_id uuid,
  p_company_id text,
  p_source_ids uuid[],
  p_edges jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_snapshot public.repository_snapshots%ROWTYPE;
  v_inserted integer;
  v_invalid integer;
BEGIN
  IF p_snapshot_id IS NULL OR p_company_id IS NULL
     OR btrim(p_company_id) = '' OR lower(btrim(p_company_id)) = 'default'
     OR p_source_ids IS NULL OR p_edges IS NULL
     OR jsonb_typeof(p_edges) <> 'array' THEN
    RAISE EXCEPTION 'snapshot, company, source IDs, and edge array are required'
      USING ERRCODE = '22023';
  END IF;

  SELECT * INTO v_snapshot
  FROM public.repository_snapshots
  WHERE id = p_snapshot_id AND company_id = p_company_id
  FOR UPDATE;

  IF NOT FOUND OR v_snapshot.status <> 'building' THEN
    RAISE EXCEPTION 'implementation edges can only be written to a building snapshot'
      USING ERRCODE = '42501';
  END IF;

  IF EXISTS (
    SELECT 1 FROM unnest(p_source_ids) s(id)
    WHERE s.id IS NULL
  ) OR cardinality(p_source_ids) <>
    (SELECT count(DISTINCT id) FROM unnest(p_source_ids) s(id)) THEN
    RAISE EXCEPTION 'source IDs must be non-null and unique' USING ERRCODE = '22023';
  END IF;

  SELECT count(*) INTO v_invalid
  FROM unnest(p_source_ids) s(id)
  WHERE NOT EXISTS (
    SELECT 1 FROM public.codebase_files f
    JOIN public.entities e ON e.company_id = p_company_id
      AND e.id = s.id AND e.type = 'FILE'
    WHERE f.snapshot_id = p_snapshot_id
      AND f.repository_id = v_snapshot.repository_id
      AND e.metadata->>'file_path' = f.file_path
      AND e.metadata->>'repository_id' = v_snapshot.repository_id::text
  );

  IF v_invalid > 0 THEN
    RAISE EXCEPTION 'source IDs must belong to the requested snapshot'
      USING ERRCODE = '42501';
  END IF;

  SELECT count(*) INTO v_invalid
  FROM jsonb_to_recordset(p_edges) AS item(
    id uuid, source_id uuid, target_id uuid, type text,
    confidence double precision, metadata jsonb,
    created_at timestamptz, company_id text
  )
  WHERE item.id IS NULL OR item.source_id IS NULL OR item.target_id IS NULL
     OR item.type NOT IN ('IMPORTS', 'ROUTE_HANDLER_OPERATION')
     OR item.confidence IS NULL OR item.confidence < 0 OR item.confidence > 1
     OR item.company_id IS DISTINCT FROM p_company_id
     OR NOT (item.source_id = ANY(p_source_ids))
     OR NOT EXISTS (
       SELECT 1
       FROM public.codebase_files target_file
       JOIN public.entities target_entity
         ON target_entity.id = item.target_id
        AND target_entity.company_id = p_company_id
        AND target_entity.type = 'FILE'
        AND target_entity.metadata->>'file_path' = target_file.file_path
        AND target_entity.metadata->>'repository_id' = v_snapshot.repository_id::text
       WHERE target_file.snapshot_id = p_snapshot_id
         AND target_file.repository_id = v_snapshot.repository_id
     );

  IF v_invalid > 0 THEN
    RAISE EXCEPTION 'replacement edges contain invalid or cross-company records'
      USING ERRCODE = '42501';
  END IF;

  DELETE FROM public.edges
  WHERE snapshot_id = p_snapshot_id
    AND company_id = p_company_id
    AND source_id = ANY(p_source_ids)
    AND type IN ('IMPORTS', 'ROUTE_HANDLER_OPERATION');

  INSERT INTO public.edges (
    id, source_id, target_id, type, confidence, metadata,
    created_at, company_id, snapshot_id
  )
  SELECT item.id, item.source_id, item.target_id, item.type,
    item.confidence, item.metadata, COALESCE(item.created_at, now()),
    item.company_id, p_snapshot_id
  FROM jsonb_to_recordset(p_edges) AS item(
    id uuid, source_id uuid, target_id uuid, type text,
    confidence double precision, metadata jsonb,
    created_at timestamptz, company_id text
  );

  GET DIAGNOSTICS v_inserted = ROW_COUNT;
  RETURN v_inserted;
END;
$$;

REVOKE ALL ON FUNCTION public.create_repository_snapshot(uuid,text,uuid,text,uuid)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.publish_repository_snapshot(uuid,uuid,integer,integer,integer,timestamptz)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fail_repository_snapshot(uuid,uuid,text)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.replace_snapshot_implementation_edges(uuid,text,uuid[],jsonb)
  FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.create_repository_snapshot(uuid,text,uuid,text,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.publish_repository_snapshot(uuid,uuid,integer,integer,integer,timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.fail_repository_snapshot(uuid,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.replace_snapshot_implementation_edges(uuid,text,uuid[],jsonb) TO service_role;

COMMIT;
