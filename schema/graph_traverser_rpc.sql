-- Company-scoped graph traversal. Drop the historical global overload so it cannot
-- remain callable without a tenant identifier.
DROP FUNCTION IF EXISTS public.search_edges_by_entity(text, text[]);

CREATE OR REPLACE FUNCTION public.search_edges_by_entity(
  search_term text,
  relation_types text[],
  filter_company_id text
)
RETURNS TABLE (
  id uuid,
  source_name text,
  target_name text,
  type text,
  confidence double precision
)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF filter_company_id IS NULL
     OR btrim(filter_company_id) = ''
     OR lower(btrim(filter_company_id)) = 'default' THEN
    RAISE EXCEPTION 'a real filter_company_id is required' USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  SELECT
    e.id,
    s.name AS source_name,
    t.name AS target_name,
    e.type,
    COALESCE((e.metadata->>'confidence')::float, e.confidence, 0.9)::double precision
  FROM public.edges AS e
  JOIN public.entities AS s
    ON s.id = e.source_id AND s.company_id = filter_company_id
  JOIN public.entities AS t
    ON t.id = e.target_id AND t.company_id = filter_company_id
  WHERE e.company_id = filter_company_id
    AND (
      lower(s.name) LIKE '%' || lower(search_term) || '%'
      OR lower(t.name) LIKE '%' || lower(search_term) || '%'
    )
    AND (cardinality(relation_types) = 0 OR e.type = ANY (relation_types))
  LIMIT 10;
END;
$$;

REVOKE ALL ON FUNCTION public.search_edges_by_entity(text, text[], text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.search_edges_by_entity(text, text[], text) TO authenticated, service_role;
