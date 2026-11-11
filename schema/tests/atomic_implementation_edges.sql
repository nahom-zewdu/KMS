-- Integration checks for 20261111_atomic_implementation_edges.sql.
-- Run only against a disposable database after applying schema/schemas.sql
-- and all migrations. The outer transaction is rolled back at the end.

BEGIN;

DO $test$
DECLARE
  v_company text := 'atomic-edge-test-company';
  v_other_company text := 'atomic-edge-other-company';
  v_source uuid := gen_random_uuid();
  v_target uuid := gen_random_uuid();
  v_foreign_target uuid := gen_random_uuid();
  v_old_edge uuid := gen_random_uuid();
  v_collision_edge uuid := gen_random_uuid();
  v_new_edge uuid := gen_random_uuid();
  v_count integer;
BEGIN
  INSERT INTO public.entities (id, type, name, company_id)
  VALUES
    (v_source, 'FILE', 'source.go', v_company),
    (v_target, 'FILE', 'target.go', v_company),
    (v_foreign_target, 'FILE', 'foreign.go', v_other_company);

  INSERT INTO public.edges
    (id, source_id, target_id, type, confidence, company_id)
  VALUES
    (v_old_edge, v_source, v_target, 'IMPORTS', 1.0, v_company),
    (v_collision_edge, v_target, v_source, 'OWNS', 0.8, v_company);

  -- Happy path: replacement removes the old implementation edge and inserts
  -- the complete new set while leaving unrelated relationship types intact.
  v_count := public.replace_implementation_edges(
    v_company,
    ARRAY[v_source]::uuid[],
    jsonb_build_array(jsonb_build_object(
      'id', v_new_edge,
      'source_id', v_source,
      'target_id', v_target,
      'type', 'ROUTE_HANDLER_OPERATION',
      'confidence', 0.8,
      'company_id', v_company,
      'metadata', jsonb_build_object('test', true)
    ))
  );

  IF v_count <> 1
     OR EXISTS (SELECT 1 FROM public.edges WHERE id = v_old_edge)
     OR NOT EXISTS (SELECT 1 FROM public.edges WHERE id = v_new_edge)
     OR NOT EXISTS (SELECT 1 FROM public.edges WHERE id = v_collision_edge) THEN
    RAISE EXCEPTION 'successful replacement did not preserve expected edge state';
  END IF;

  -- Failure path: the replacement insert collides with an unrelated existing
  -- edge ID. Catching the exception creates a subtransaction; the function's
  -- preceding DELETE must have rolled back with its failed INSERT.
  BEGIN
    PERFORM public.replace_implementation_edges(
      v_company,
      ARRAY[v_source]::uuid[],
      jsonb_build_array(jsonb_build_object(
        'id', v_collision_edge,
        'source_id', v_source,
        'target_id', v_target,
        'type', 'IMPORTS',
        'confidence', 1.0,
        'company_id', v_company
      ))
    );
    RAISE EXCEPTION 'expected primary-key collision was not raised';
  EXCEPTION WHEN unique_violation THEN
    NULL;
  END;

  IF NOT EXISTS (SELECT 1 FROM public.edges WHERE id = v_new_edge) THEN
    RAISE EXCEPTION 'failed replacement deleted the previously committed edge';
  END IF;

  -- Cross-company endpoint must be rejected and leave the prior edge intact.
  BEGIN
    PERFORM public.replace_implementation_edges(
      v_company,
      ARRAY[v_source]::uuid[],
      jsonb_build_array(jsonb_build_object(
        'id', gen_random_uuid(),
        'source_id', v_source,
        'target_id', v_foreign_target,
        'type', 'IMPORTS',
        'confidence', 1.0,
        'company_id', v_company
      ))
    );
    RAISE EXCEPTION 'cross-company endpoint was not rejected';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM = 'cross-company endpoint was not rejected' THEN
      RAISE;
    END IF;
  END;

  IF NOT EXISTS (SELECT 1 FROM public.edges WHERE id = v_new_edge) THEN
    RAISE EXCEPTION 'tenant validation failure deleted the previous edge';
  END IF;

  -- Duplicate and null source IDs must be rejected before replacement.
  BEGIN
    PERFORM public.replace_implementation_edges(
      v_company,
      ARRAY[v_source, v_source]::uuid[],
      '[]'::jsonb
    );
    RAISE EXCEPTION 'duplicate source IDs were not rejected';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM = 'duplicate source IDs were not rejected' THEN
      RAISE;
    END IF;
  END;

  RAISE NOTICE 'atomic implementation edge integration checks passed';
END
$test$;

ROLLBACK;
