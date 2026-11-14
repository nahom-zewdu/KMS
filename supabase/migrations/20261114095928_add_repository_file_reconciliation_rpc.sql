-- Remove stale repository files/entities only after a complete immutable
-- repository snapshot has been traversed and indexed successfully.
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
