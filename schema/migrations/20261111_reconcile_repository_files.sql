BEGIN;

CREATE OR REPLACE FUNCTION public.reconcile_repository_files(
  p_repository_id uuid,
  p_company_id text,
  p_live_paths text[]
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_deleted integer := 0;
BEGIN
  IF p_repository_id IS NULL
     OR nullif(btrim(p_company_id), '') IS NULL
     OR lower(btrim(p_company_id)) = 'default'
     OR p_live_paths IS NULL THEN
    RAISE EXCEPTION 'repository, company, and complete live path inventory are required';
  END IF;

  IF EXISTS (
    SELECT 1 FROM unnest(p_live_paths) AS p(path)
    WHERE p.path IS NULL OR btrim(p.path) = ''
  ) OR cardinality(p_live_paths) <> (
    SELECT count(DISTINCT p.path) FROM unnest(p_live_paths) AS p(path)
  ) THEN
    RAISE EXCEPTION 'live paths must be non-empty and unique';
  END IF;

  PERFORM pg_advisory_xact_lock(
    hashtext('kms-repository-file-reconciliation'),
    hashtext(p_repository_id::text)
  );

  CREATE TEMP TABLE IF NOT EXISTS stale_repository_files (
    codebase_file_id uuid NOT NULL,
    entity_id uuid NOT NULL
  ) ON COMMIT DROP;
  TRUNCATE TABLE pg_temp.stale_repository_files;

  INSERT INTO pg_temp.stale_repository_files (codebase_file_id, entity_id)
  SELECT f.id, e.id
  FROM public.repositories r
  JOIN public.entities repo_entity
    ON repo_entity.type = 'REPOSITORY'
   AND repo_entity.name = r.full_name
   AND repo_entity.company_id = r.company_id
  JOIN public.edges membership
    ON membership.type = 'PART_OF'
   AND membership.target_id = repo_entity.id
   AND membership.company_id = r.company_id
  JOIN public.entities e
    ON e.id = membership.source_id
   AND e.type = 'FILE'
   AND e.company_id = r.company_id
  JOIN public.codebase_files f
    ON f.repository_id = r.id
   AND e.metadata->>'file_path' = f.file_path
  WHERE r.id = p_repository_id
    AND r.company_id = p_company_id
    AND NOT (f.file_path = ANY(p_live_paths));

  IF NOT EXISTS (
    SELECT 1 FROM public.repositories r
    WHERE r.id = p_repository_id AND r.company_id = p_company_id
  ) THEN
    RAISE EXCEPTION 'repository does not belong to requested company';
  END IF;

  DELETE FROM public.edges edge
  USING stale_repository_files stale
  WHERE edge.company_id = p_company_id
    AND (edge.source_id = stale.entity_id OR edge.target_id = stale.entity_id);

  DELETE FROM public.entities entity
  USING stale_repository_files stale
  WHERE entity.id = stale.entity_id
    AND entity.company_id = p_company_id
    AND entity.type = 'FILE';

  DELETE FROM public.codebase_files f
  USING stale_repository_files stale
  WHERE f.id = stale.codebase_file_id
    AND f.repository_id = p_repository_id;

  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN v_deleted;
END;
$$;

REVOKE ALL ON FUNCTION public.reconcile_repository_files(uuid, text, text[])
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reconcile_repository_files(uuid, text, text[])
  TO service_role;

COMMIT;
