-- Integration checks for 20261111_reconcile_repository_files.sql.
-- Run against a disposable database after applying schema/schemas.sql and
-- all prerequisite migrations. All fixture data is rolled back.

BEGIN;

DO $test$
DECLARE
  v_company text := 'file-reconcile-test-company';
  v_other_company text := 'file-reconcile-other-company';
  v_repo uuid := gen_random_uuid();
  v_other_repo uuid := gen_random_uuid();
  v_repo_entity uuid := gen_random_uuid();
  v_other_repo_entity uuid := gen_random_uuid();
  v_stale_file uuid := gen_random_uuid();
  v_live_file uuid := gen_random_uuid();
  v_other_file uuid := gen_random_uuid();
  v_stale_row uuid := gen_random_uuid();
  v_live_row uuid := gen_random_uuid();
  v_other_row uuid := gen_random_uuid();
  v_stale_partof uuid := gen_random_uuid();
  v_live_partof uuid := gen_random_uuid();
  v_other_partof uuid := gen_random_uuid();
  v_stale_import uuid := gen_random_uuid();
  v_deleted integer;
BEGIN
  INSERT INTO public.companies (id, name)
  VALUES (v_company, 'File reconciliation test'),
         (v_other_company, 'Other file reconciliation test');

  INSERT INTO public.repositories (id, company_id, full_name)
  VALUES (v_repo, v_company, 'test-owner/reconcile'),
         (v_other_repo, v_other_company, 'other-owner/reconcile');

  INSERT INTO public.entities (id, type, name, company_id, metadata)
  VALUES
    (v_repo_entity, 'REPOSITORY', 'test-owner/reconcile', v_company, '{}'),
    (v_other_repo_entity, 'REPOSITORY', 'other-owner/reconcile', v_other_company, '{}'),
    (v_stale_file, 'FILE', 'removed.go', v_company,
      jsonb_build_object('file_path', 'src/removed.go')),
    (v_live_file, 'FILE', 'live.go', v_company,
      jsonb_build_object('file_path', 'src/live.go')),
    (v_other_file, 'FILE', 'removed.go', v_other_company,
      jsonb_build_object('file_path', 'src/removed.go'));

  INSERT INTO public.codebase_files
    (id, repository_id, file_path, file_name)
  VALUES
    (v_stale_row, v_repo, 'src/removed.go', 'removed.go'),
    (v_live_row, v_repo, 'src/live.go', 'live.go'),
    (v_other_row, v_other_repo, 'src/removed.go', 'removed.go');

  INSERT INTO public.edges
    (id, source_id, target_id, type, company_id)
  VALUES
    (v_stale_partof, v_stale_file, v_repo_entity, 'PART_OF', v_company),
    (v_live_partof, v_live_file, v_repo_entity, 'PART_OF', v_company),
    (v_other_partof, v_other_file, v_other_repo_entity, 'PART_OF', v_other_company),
    (v_stale_import, v_stale_file, v_live_file, 'IMPORTS', v_company);

  -- A successful inventory reconciliation removes the deleted path, its FILE
  -- entity, and every incident graph edge, but preserves live and foreign data.
  v_deleted := public.reconcile_repository_files(
    v_repo, v_company, ARRAY['src/live.go']::text[]
  );

  IF v_deleted <> 1
     OR EXISTS (SELECT 1 FROM public.codebase_files WHERE id = v_stale_row)
     OR EXISTS (SELECT 1 FROM public.entities WHERE id = v_stale_file)
     OR EXISTS (SELECT 1 FROM public.edges WHERE id IN (v_stale_partof, v_stale_import))
     OR NOT EXISTS (SELECT 1 FROM public.codebase_files WHERE id = v_live_row)
     OR NOT EXISTS (SELECT 1 FROM public.entities WHERE id = v_live_file)
     OR NOT EXISTS (SELECT 1 FROM public.edges WHERE id = v_live_partof)
     OR NOT EXISTS (SELECT 1 FROM public.codebase_files WHERE id = v_other_row)
     OR NOT EXISTS (SELECT 1 FROM public.entities WHERE id = v_other_file)
     OR NOT EXISTS (SELECT 1 FROM public.edges WHERE id = v_other_partof) THEN
    RAISE EXCEPTION 'repository reconciliation did not preserve the expected tenant/repository boundaries';
  END IF;

  -- Empty inventory is valid and means the repository has no files.
  v_deleted := public.reconcile_repository_files(v_repo, v_company, ARRAY[]::text[]);
  IF v_deleted <> 1
     OR EXISTS (SELECT 1 FROM public.codebase_files WHERE id = v_live_row)
     OR EXISTS (SELECT 1 FROM public.entities WHERE id = v_live_file) THEN
    RAISE EXCEPTION 'empty complete inventory did not remove remaining repository files';
  END IF;

  -- A tenant mismatch must fail without touching the foreign repository.
  BEGIN
    PERFORM public.reconcile_repository_files(
      v_other_repo, v_company, ARRAY[]::text[]
    );
    RAISE EXCEPTION 'cross-company repository reconciliation was not rejected';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM <> 'repository does not belong to requested company' THEN
      RAISE;
    END IF;
  END;

  IF NOT EXISTS (SELECT 1 FROM public.codebase_files WHERE id = v_other_row)
     OR NOT EXISTS (SELECT 1 FROM public.entities WHERE id = v_other_file) THEN
    RAISE EXCEPTION 'rejected cross-company reconciliation changed foreign data';
  END IF;

  -- Invalid duplicate paths must be rejected before any destructive operation.
  BEGIN
    PERFORM public.reconcile_repository_files(
      v_other_repo, v_other_company,
      ARRAY['src/removed.go', 'src/removed.go']::text[]
    );
    RAISE EXCEPTION 'duplicate live paths were not rejected';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM <> 'live paths must be non-empty and unique' THEN
      RAISE;
    END IF;
  END;

  RAISE NOTICE 'repository file reconciliation integration checks passed';
END
$test$;

ROLLBACK;
