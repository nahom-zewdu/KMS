BEGIN;

-- The original reset schema omitted confidence even though the application
-- already writes it for graph edges. Make the column explicit before the RPC
-- references it, preserving existing rows with a neutral default.
ALTER TABLE public.edges
  ADD COLUMN IF NOT EXISTS confidence double precision NOT NULL DEFAULT 1.0;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.edges'::regclass
      AND conname = 'edges_confidence_range'
  ) THEN
    ALTER TABLE public.edges
      ADD CONSTRAINT edges_confidence_range
      CHECK (confidence >= 0 AND confidence <= 1) NOT VALID;
  END IF;
END $$;

ALTER TABLE public.edges VALIDATE CONSTRAINT edges_confidence_range;

CREATE OR REPLACE FUNCTION public.replace_implementation_edges(
  p_company_id text,
  p_source_ids uuid[],
  p_edges jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_count integer := 0;
BEGIN
  IF nullif(btrim(p_company_id), '') IS NULL
     OR lower(btrim(p_company_id)) = 'default' THEN
    RAISE EXCEPTION 'a valid company_id is required';
  END IF;
  IF p_source_ids IS NULL
     OR cardinality(p_source_ids) = 0
     OR array_position(p_source_ids, NULL::uuid) IS NOT NULL
     OR cardinality(p_source_ids) <> (
       SELECT count(DISTINCT requested.source_id)
       FROM unnest(p_source_ids) AS requested(source_id)
     ) THEN
    RAISE EXCEPTION 'source file identities must be non-empty, non-null, and unique';
  END IF;
  IF p_edges IS NULL OR jsonb_typeof(p_edges) <> 'array' THEN
    RAISE EXCEPTION 'edges must be a JSON array';
  END IF;

  -- Serialize relationship replacements within a tenant. The lock is held
  -- until transaction completion, so concurrent indexers cannot interleave
  -- delete/insert phases for the same company.
  PERFORM pg_advisory_xact_lock(
    hashtext('kms-implementation-edge-replacement'),
    hashtext(p_company_id)
  );

  -- Validate the entire replacement set before deleting anything.
  IF (
    SELECT count(DISTINCT entity.id)
    FROM public.entities AS entity
    WHERE entity.id = ANY(p_source_ids)
      AND entity.company_id = p_company_id
      AND entity.type = 'FILE'
  ) <> (
    SELECT count(DISTINCT source_id)
    FROM unnest(p_source_ids) AS requested(source_id)
  ) THEN
    RAISE EXCEPTION 'all source entities must belong to the requested company';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM jsonb_to_recordset(p_edges) AS e(
      id uuid,
      source_id uuid,
      target_id uuid,
      type text,
      confidence double precision,
      company_id text
    )
    WHERE e.id IS NULL
       OR e.source_id IS NULL
       OR e.target_id IS NULL
       OR e.source_id <> ALL(p_source_ids)
       OR e.type IS NULL
       OR e.type NOT IN ('IMPORTS', 'ROUTE_HANDLER_OPERATION')
       OR e.company_id IS DISTINCT FROM p_company_id
       OR e.confidence IS NULL
       OR e.confidence < 0
       OR e.confidence > 1
  ) THEN
    RAISE EXCEPTION 'replacement edges contain invalid identity, tenant, type, or confidence';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM jsonb_to_recordset(p_edges) AS e(source_id uuid, target_id uuid)
    LEFT JOIN public.entities AS source_entity ON source_entity.id = e.source_id
    LEFT JOIN public.entities AS target_entity ON target_entity.id = e.target_id
    WHERE source_entity.company_id IS DISTINCT FROM p_company_id
       OR target_entity.company_id IS DISTINCT FROM p_company_id
       OR source_entity.type IS DISTINCT FROM 'FILE'
       OR target_entity.type IS DISTINCT FROM 'FILE'
  ) THEN
    RAISE EXCEPTION 'replacement edge endpoints must belong to the requested company';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM jsonb_to_recordset(p_edges) AS e(id uuid)
    GROUP BY e.id
    HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION 'replacement edge IDs must be unique';
  END IF;

  DELETE FROM public.edges
  WHERE company_id = p_company_id
    AND source_id = ANY(p_source_ids)
    AND type IN ('IMPORTS', 'ROUTE_HANDLER_OPERATION');

  INSERT INTO public.edges
    (id, source_id, target_id, type, confidence, metadata, created_at, company_id)
  SELECT
    e.id, e.source_id, e.target_id, e.type, e.confidence,
    e.metadata, coalesce(e.created_at, now()), p_company_id
  FROM jsonb_to_recordset(p_edges) AS e(
    id uuid,
    source_id uuid,
    target_id uuid,
    type text,
    confidence double precision,
    metadata jsonb,
    created_at timestamptz
  );

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.replace_implementation_edges(text, uuid[], jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.replace_implementation_edges(text, uuid[], jsonb)
  TO service_role;

COMMIT;
