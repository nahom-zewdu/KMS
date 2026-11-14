-- Atomically replace implementation relationships for a repository snapshot.
-- The caller supplies all indexed FILE entity IDs and the complete extracted
-- relationship set for one company. Unrelated edge types are preserved.

CREATE OR REPLACE FUNCTION public.replace_implementation_edges(
  p_company_id text,
  p_source_ids uuid[],
  p_edges jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
  inserted_count integer;
  invalid_count integer;
BEGIN
  IF p_company_id IS NULL
     OR btrim(p_company_id) = ''
     OR lower(btrim(p_company_id)) = 'default'
     OR p_source_ids IS NULL
     OR p_edges IS NULL
     OR jsonb_typeof(p_edges) <> 'array' THEN
    RAISE EXCEPTION 'valid company_id, source_ids, and edges array are required';
  END IF;

  SELECT count(*) INTO invalid_count
  FROM unnest(p_source_ids) AS supplied(id)
  WHERE NOT EXISTS (
    SELECT 1 FROM public.entities e
    WHERE e.id = supplied.id
      AND e.company_id = p_company_id
      AND e.type = 'FILE'
  );
  IF invalid_count > 0 THEN
    RAISE EXCEPTION 'source_ids contain entities outside the requested company';
  END IF;

  SELECT count(*) INTO invalid_count
  FROM jsonb_to_recordset(p_edges) AS item(
    id uuid,
    source_id uuid,
    target_id uuid,
    type text,
    confidence double precision,
    metadata jsonb,
    created_at timestamptz,
    company_id text
  )
  WHERE item.id IS NULL
     OR item.source_id IS NULL
     OR item.target_id IS NULL
     OR item.type NOT IN ('IMPORTS', 'ROUTE_HANDLER_OPERATION')
     OR item.confidence IS NULL
     OR item.confidence < 0
     OR item.confidence > 1
     OR item.company_id IS DISTINCT FROM p_company_id
     OR NOT (item.source_id = ANY(p_source_ids))
     OR NOT EXISTS (
       SELECT 1 FROM public.entities source_entity
       WHERE source_entity.id = item.source_id
         AND source_entity.company_id = p_company_id
         AND source_entity.type = 'FILE'
     )
     OR NOT EXISTS (
       SELECT 1 FROM public.entities target_entity
       WHERE target_entity.id = item.target_id
         AND target_entity.company_id = p_company_id
     );

  IF invalid_count > 0 THEN
    RAISE EXCEPTION 'replacement edges contain invalid, cross-company, or unsupported records';
  END IF;

  DELETE FROM public.edges
  WHERE company_id = p_company_id
    AND source_id = ANY(p_source_ids)
    AND type IN ('IMPORTS', 'ROUTE_HANDLER_OPERATION');

  INSERT INTO public.edges (
    id, source_id, target_id, type, confidence, metadata, created_at, company_id
  )
  SELECT
    item.id,
    item.source_id,
    item.target_id,
    item.type,
    item.confidence,
    item.metadata,
    COALESCE(item.created_at, now()),
    item.company_id
  FROM jsonb_to_recordset(p_edges) AS item(
    id uuid,
    source_id uuid,
    target_id uuid,
    type text,
    confidence double precision,
    metadata jsonb,
    created_at timestamptz,
    company_id text
  );

  GET DIAGNOSTICS inserted_count = ROW_COUNT;
  RETURN inserted_count;
END;
$$;

REVOKE ALL ON FUNCTION public.replace_implementation_edges(text, uuid[], jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.replace_implementation_edges(text, uuid[], jsonb) TO service_role;
