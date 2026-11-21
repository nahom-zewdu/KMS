-- Integration coverage for revision-pinned SCIP occurrence persistence.
-- Run after all migrations against a disposable PostgreSQL database.
-- All fixture data is rolled back.

BEGIN;

DO $test$
DECLARE
  v_company text := 'occurrence-test-' || gen_random_uuid()::text;
  v_repo uuid := gen_random_uuid();
  v_run uuid := gen_random_uuid();
  v_snapshot uuid := gen_random_uuid();
  v_count integer;
BEGIN
  INSERT INTO public.companies (id, name)
  VALUES (v_company, 'SCIP occurrence test');

  INSERT INTO public.repositories (
    id, company_id, full_name,
    baseline_status, baseline_run_id, baseline_lease_expires_at
  ) VALUES (
    v_repo, v_company, 'occurrence-test/repository',
    'indexing', v_run, now() + interval '10 minutes'
  );

  PERFORM public.create_repository_snapshot(
    v_repo, v_company, v_run, repeat('a', 40), v_snapshot
  );

  INSERT INTO public.codebase_files (
    id, repository_id, file_path, snapshot_id
  ) VALUES (
    gen_random_uuid(), v_repo, 'src/main.py', v_snapshot
  );

  INSERT INTO public.code_symbol_occurrences (
    repository_id, snapshot_id, company_id, occurrence_id, file_path,
    symbol, role, symbol_roles, start_line, end_line, start_byte, end_byte,
    content_hash, source_revision, indexer_name, indexer_version, protocol_version
  ) VALUES (
    v_repo, v_snapshot, v_company, repeat('b', 64), 'src/main.py',
    'scip-python python pkg/main.py/normalize().', 'definition', 1,
    1, 1, 0, 9, repeat('c', 64), repeat('a', 40),
    'scip-python', '0.6.8', 1
  );

  -- Idempotent retry: the same stable occurrence identity must update, not duplicate.
  INSERT INTO public.code_symbol_occurrences (
    repository_id, snapshot_id, company_id, occurrence_id, file_path,
    symbol, role, symbol_roles, start_line, end_line, start_byte, end_byte,
    content_hash, source_revision, indexer_name, indexer_version, protocol_version
  ) VALUES (
    v_repo, v_snapshot, v_company, repeat('b', 64), 'src/main.py',
    'scip-python python pkg/main.py/normalize().', 'definition', 1,
    1, 1, 0, 9, repeat('c', 64), repeat('a', 40),
    'scip-python', '0.6.8', 1
  )
  ON CONFLICT (snapshot_id, occurrence_id)
  DO UPDATE SET role = EXCLUDED.role;

  SELECT count(*) INTO v_count
  FROM public.code_symbol_occurrences
  WHERE snapshot_id = v_snapshot;
  IF v_count <> 1 THEN
    RAISE EXCEPTION 'idempotent occurrence retry created % rows', v_count;
  END IF;

  -- A different revision cannot be written into this snapshot.
  BEGIN
    INSERT INTO public.code_symbol_occurrences (
      repository_id, snapshot_id, company_id, occurrence_id, file_path,
      symbol, role, symbol_roles, start_line, end_line, start_byte, end_byte,
      content_hash, source_revision, indexer_name, indexer_version, protocol_version
    ) VALUES (
      v_repo, v_snapshot, v_company, repeat('d', 64), 'src/main.py',
      'scip-python python pkg/main.py/other().', 'reference', 8,
      1, 1, 10, 15, repeat('c', 64), repeat('d', 40),
      'scip-python', '0.6.8', 1
    );
    RAISE EXCEPTION 'mismatched occurrence revision unexpectedly persisted';
  EXCEPTION WHEN check_violation THEN NULL;
  END;

  -- A path absent from this snapshot is rejected by the composite file FK.
  BEGIN
    INSERT INTO public.code_symbol_occurrences (
      repository_id, snapshot_id, company_id, occurrence_id, file_path,
      symbol, role, symbol_roles, start_line, end_line, start_byte, end_byte,
      content_hash, source_revision, indexer_name, indexer_version, protocol_version
    ) VALUES (
      v_repo, v_snapshot, v_company, repeat('e', 64), 'src/missing.py',
      'scip-python python pkg/main.py/missing().', 'reference', 8,
      1, 1, 10, 15, repeat('c', 64), repeat('a', 40),
      'scip-python', '0.6.8', 1
    );
    RAISE EXCEPTION 'occurrence for a file outside the snapshot unexpectedly persisted';
  EXCEPTION WHEN foreign_key_violation THEN NULL;
  END;

  -- Publication cannot proceed until the declared occurrence count matches.
  BEGIN
    UPDATE public.repository_snapshots
    SET status = 'published', occurrence_count = 0
    WHERE id = v_snapshot;
    RAISE EXCEPTION 'publication accepted an incorrect occurrence count';
  EXCEPTION WHEN check_violation THEN NULL;
  END;

  IF public.refresh_snapshot_occurrence_validation(v_snapshot, v_company) <> 1 THEN
    RAISE EXCEPTION 'occurrence coverage refresh returned an incorrect count';
  END IF;

  UPDATE public.repository_snapshots
  SET status = 'published'
  WHERE id = v_snapshot;

  -- Once published, the row-level trigger rejects mutation.
  BEGIN
    UPDATE public.code_symbol_occurrences
    SET role = 'reference'
    WHERE snapshot_id = v_snapshot;
    RAISE EXCEPTION 'published occurrence unexpectedly changed';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;

  RAISE NOTICE 'SCIP occurrence persistence integration checks passed';
END
$test$;

ROLLBACK;
