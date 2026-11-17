-- Integration tests for tenant- and snapshot-scoped code symbol persistence.
-- Run after all migrations against a disposable PostgreSQL database.
BEGIN;

DO $test$
DECLARE
  v_company text := 'code-symbol-test-' || gen_random_uuid()::text;
  v_other_company text := 'code-symbol-other-' || gen_random_uuid()::text;
  v_repo uuid := gen_random_uuid();
  v_other_repo uuid := gen_random_uuid();
  v_run uuid := gen_random_uuid();
  v_snapshot uuid := gen_random_uuid();
  v_symbol uuid := gen_random_uuid();
  v_revision text := repeat('a', 40);
  v_failed boolean := false;
BEGIN
  INSERT INTO public.companies (id, name)
  VALUES (v_company, 'Code symbol test'), (v_other_company, 'Other tenant');

  INSERT INTO public.repositories (
    id, company_id, full_name, baseline_status, baseline_run_id,
    baseline_lease_expires_at
  ) VALUES
    (v_repo, v_company, 'symbols-test/repository', 'indexing', v_run, now() + interval '10 minutes'),
    (v_other_repo, v_other_company, 'other/repository', 'indexing', gen_random_uuid(), now() + interval '10 minutes');

  INSERT INTO public.repository_snapshots (
    id, repository_id, company_id, source_revision, run_id, status
  ) VALUES (v_snapshot, v_repo, v_company, v_revision, v_run, 'building');

  INSERT INTO public.codebase_files (
    id, repository_id, file_path, file_name, snapshot_id
  ) VALUES (gen_random_uuid(), v_repo, 'src/worker.py', 'worker.py', v_snapshot);

  INSERT INTO public.code_symbols (
    id, repository_id, snapshot_id, company_id, symbol_id, file_path,
    language, name, qualified_name, kind, start_line, end_line,
    start_byte, end_byte, content_hash, source_revision, extractor_version
  ) VALUES (
    v_symbol, v_repo, v_snapshot, v_company, repeat('b', 64),
    'src/worker.py', 'Python', 'Worker', 'Worker', 'class',
    1, 8, 0, 120, repeat('c', 64), v_revision, '1'
  );

  IF (SELECT count(*) FROM public.code_symbols WHERE snapshot_id = v_snapshot) <> 1 THEN
    RAISE EXCEPTION 'expected persisted symbol row';
  END IF;

  -- A symbol cannot claim another tenant's company scope.
  BEGIN
    INSERT INTO public.code_symbols (
      repository_id, snapshot_id, company_id, symbol_id, file_path,
      language, name, qualified_name, kind, start_line, end_line,
      start_byte, end_byte, content_hash, source_revision, extractor_version
    ) VALUES (
      v_repo, v_snapshot, v_other_company, repeat('d', 64), 'src/worker.py',
      'Python', 'run', 'run', 'function', 10, 11, 121, 140,
      repeat('e', 64), v_revision, '1'
    );
  EXCEPTION
    WHEN insufficient_privilege OR foreign_key_violation THEN
      v_failed := true;
  END;
  IF NOT v_failed THEN
    RAISE EXCEPTION 'cross-tenant symbol row was accepted';
  END IF;

  -- A symbol cannot be attached to a different source revision.
  v_failed := false;
  BEGIN
    INSERT INTO public.code_symbols (
      repository_id, snapshot_id, company_id, symbol_id, file_path,
      language, name, qualified_name, kind, start_line, end_line,
      start_byte, end_byte, content_hash, source_revision, extractor_version
    ) VALUES (
      v_repo, v_snapshot, v_company, repeat('f', 64), 'src/worker.py',
      'Python', 'run', 'run', 'function', 10, 11, 121, 140,
      repeat('e', 64), repeat('9', 40), '1'
    );
  EXCEPTION WHEN check_violation THEN
    v_failed := true;
  END;
  IF NOT v_failed THEN
    RAISE EXCEPTION 'revision-mismatched symbol row was accepted';
  END IF;

  -- Publication must reject a count that does not match persisted declarations.
  v_failed := false;
  BEGIN
    UPDATE public.repository_snapshots
    SET symbol_count = 2, status = 'published', completed_at = now()
    WHERE id = v_snapshot;
  EXCEPTION WHEN check_violation THEN
    v_failed := true;
  END;
  IF NOT v_failed THEN
    RAISE EXCEPTION 'snapshot published with an incorrect symbol count';
  END IF;
  IF (SELECT status FROM public.repository_snapshots WHERE id = v_snapshot) <> 'building' THEN
    RAISE EXCEPTION 'failed symbol-count validation changed snapshot status';
  END IF;

  UPDATE public.repository_snapshots
  SET symbol_count = 1, status = 'published', completed_at = now()
  WHERE id = v_snapshot;

  -- Published snapshots are immutable to the symbol writer.
  v_failed := false;
  BEGIN
    INSERT INTO public.code_symbols (
      repository_id, snapshot_id, company_id, symbol_id, file_path,
      language, name, qualified_name, kind, start_line, end_line,
      start_byte, end_byte, content_hash, source_revision, extractor_version
    ) VALUES (
      v_repo, v_snapshot, v_company, repeat('1', 64), 'src/worker.py',
      'Python', 'late', 'late', 'function', 12, 13, 141, 160,
      repeat('2', 64), v_revision, '1'
    );
  EXCEPTION WHEN insufficient_privilege THEN
    v_failed := true;
  END;
  IF NOT v_failed THEN
    RAISE EXCEPTION 'published snapshot accepted a late symbol write';
  END IF;

  RAISE NOTICE 'code symbol persistence integration checks passed';
END
$test$;

ROLLBACK;
