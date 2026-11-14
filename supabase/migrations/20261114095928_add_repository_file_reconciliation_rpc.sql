-- Remove stale physical file rows only after the worker has traversed and
-- indexed the complete immutable Git tree. Graph entity cleanup is deliberately
-- deferred until FILE entities carry an unambiguous repository identity.
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
END;
$$;

REVOKE ALL ON FUNCTION public.reconcile_repository_files(uuid, text, text[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.reconcile_repository_files(uuid, text, text[]) TO service_role;
