-- Additive schema migration for GitHub repository baseline indexing.
-- Safe to apply to existing environments; does not reset or drop application data.

ALTER TABLE public.repositories
  ADD COLUMN IF NOT EXISTS baseline_status text NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS baseline_started_at timestamptz,
  ADD COLUMN IF NOT EXISTS baseline_completed_at timestamptz,
  ADD COLUMN IF NOT EXISTS baseline_error text,
  ADD COLUMN IF NOT EXISTS baseline_file_count integer,
  ADD COLUMN IF NOT EXISTS baseline_revision text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.repositories'::regclass
      AND conname = 'repositories_baseline_status_check'
  ) THEN
    ALTER TABLE public.repositories
      ADD CONSTRAINT repositories_baseline_status_check
      CHECK (baseline_status IN ('pending', 'indexing', 'ready', 'failed'));
  END IF;
END
$$;

-- Reconcile only after the worker has successfully traversed and indexed the
-- complete immutable Git tree. The RPC removes stale files/entities for this
-- repository/company while preserving all other tenants and entity types.
CREATE OR REPLACE FUNCTION public.reconcile_repository_files(
  p_repository_id uuid,
  p_company_id text,
  p_live_paths text[]
)
RETURNS void
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
  stale_entity_ids uuid[];
BEGIN
  IF p_repository_id IS NULL
     OR p_company_id IS NULL
     OR btrim(p_company_id) = ''
     OR lower(btrim(p_company_id)) = 'default'
     OR p_live_paths IS NULL THEN
    RAISE EXCEPTION 'repository_id, valid company_id, and complete live_paths are required';
  END IF;

  DELETE FROM public.codebase_files
  WHERE repository_id = p_repository_id
    AND NOT (file_path = ANY(p_live_paths));

  SELECT array_agg(id)
    INTO stale_entity_ids
  FROM public.entities
  WHERE company_id = p_company_id
    AND type = 'FILE'
    AND metadata ? 'file_path'
    AND NOT ((metadata ->> 'file_path') = ANY(p_live_paths));

  IF COALESCE(array_length(stale_entity_ids, 1), 0) > 0 THEN
    DELETE FROM public.edges
    WHERE company_id = p_company_id
      AND (source_id = ANY(stale_entity_ids) OR target_id = ANY(stale_entity_ids));

    DELETE FROM public.entities
    WHERE company_id = p_company_id
      AND id = ANY(stale_entity_ids);
  END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.reconcile_repository_files(uuid, text, text[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.reconcile_repository_files(uuid, text, text[]) TO service_role;
