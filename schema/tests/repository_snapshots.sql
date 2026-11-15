-- Integration coverage for immutable repository snapshot staging/publication.
-- Run after all migrations against a disposable PostgreSQL database.
-- All fixture data is rolled back.

BEGIN;

DO $test$
DECLARE
  v_company text := 'snapshot-test-' || gen_random_uuid()::text;
  v_repo uuid := gen_random_uuid();
  v_run uuid := gen_random_uuid();
  v_snapshot uuid := gen_random_uuid();
  v_failed_run uuid := gen_random_uuid();
  v_failed_snapshot uuid := gen_random_uuid();
  v_source uuid := gen_random_uuid();
  v_target uuid := gen_random_uuid();
  v_edge uuid := gen_random_uuid();
  v_published boolean;
BEGIN
  INSERT INTO public.companies (id, name)
  VALUES (v_company, 'Repository snapshot test');

  INSERT INTO public.repositories (
    id, company_id, full_name,
    baseline_status, baseline_run_id, baseline_lease_expires_at
  ) VALUES (
    v_repo, v_company, 'snapshot-test/repository',
    'indexing', v_run, now() + interval '10 minutes'
  );

  PERFORM public.create_repository_snapshot(
    v_repo, v_company, v_run, repeat('a', 40), v_snapshot
  );

  INSERT INTO public.entities (id, type, name, company_id, metadata)
  VALUES
    (v_source, 'FILE', 'source.go', v_company,
      jsonb_build_object('file_path', 'src/source.go', 'repository_id', v_repo::text)),
    (v_target, 'FILE', 'target.go', v_company,
      jsonb_build_object('file_path', 'src/target.go', 'repository_id', v_repo::text));

  INSERT INTO public.codebase_files (
    id, repository_id, file_path, snapshot_id
  ) VALUES
    (gen_random_uuid(), v_repo, 'src/source.go', v_snapshot),
    (gen_random_uuid(), v_repo, 'src/target.go', v_snapshot);

  INSERT INTO public.codebase_modules (
    id, repository_id, module_path, snapshot_id
  ) VALUES (
    gen_random_uuid(), v_repo, 'src', v_snapshot
  );

  PERFORM public.replace_snapshot_implementation_edges(
    v_snapshot,
    v_company,
    ARRAY[v_source]::uuid[],
    jsonb_build_array(jsonb_build_object(
      'id', v_edge,
      'source_id', v_source,
      'target_id', v_target,
      'type', 'IMPORTS',
      'confidence', 1.0,
      'company_id', v_company,
      'metadata', jsonb_build_object('source_revision', repeat('a', 40))
    ))
  );

  v_published := public.publish_repository_snapshot(
    v_snapshot, v_run, 2, 1, 1, now()
  );

  IF NOT v_published
     OR NOT EXISTS (
       SELECT 1 FROM public.repositories
       WHERE id = v_repo AND active_snapshot_id = v_snapshot
         AND baseline_status = 'ready'
         AND baseline_revision = repeat('a', 40)
     )
     OR NOT EXISTS (
       SELECT 1 FROM public.repository_snapshots
       WHERE id = v_snapshot AND status = 'published'
     )
     OR NOT EXISTS (
       SELECT 1 FROM public.edges
       WHERE id = v_edge AND snapshot_id = v_snapshot
     ) THEN
    RAISE EXCEPTION 'complete snapshot was not atomically published';
  END IF;

  -- A failed subsequent build must not replace or invalidate the last good
  -- snapshot. Its staged rows are isolated and remain unpublished.
  UPDATE public.repositories
  SET baseline_status = 'indexing',
      baseline_run_id = v_failed_run,
      baseline_lease_expires_at = now() + interval '10 minutes'
  WHERE id = v_repo;

  PERFORM public.create_repository_snapshot(
    v_repo, v_company, v_failed_run, repeat('b', 40), v_failed_snapshot
  );

  INSERT INTO public.codebase_files (
    id, repository_id, file_path, snapshot_id
  ) VALUES (
    gen_random_uuid(), v_repo, 'src/partial.go', v_failed_snapshot
  );

  IF NOT public.fail_repository_snapshot(
    v_failed_snapshot, v_failed_run, 'simulated traversal failure'
  ) THEN
    RAISE EXCEPTION 'snapshot failure transition was rejected';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM public.repositories
    WHERE id = v_repo AND active_snapshot_id = v_snapshot
      AND baseline_status = 'ready'
      AND baseline_revision = repeat('a', 40)
  ) OR NOT EXISTS (
    SELECT 1 FROM public.repository_snapshots
    WHERE id = v_failed_snapshot AND status = 'failed'
  ) OR NOT EXISTS (
    SELECT 1 FROM public.codebase_files
    WHERE repository_id = v_repo AND snapshot_id = v_failed_snapshot
      AND file_path = 'src/partial.go'
  ) THEN
    RAISE EXCEPTION 'failed snapshot damaged the active snapshot or lost failure isolation';
  END IF;

  RAISE NOTICE 'repository snapshot publication integration checks passed';
END
$test$;

ROLLBACK;
