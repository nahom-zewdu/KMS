-- Source chunk snapshot, revision, tenant and publication integration checks.
-- Run after migrations against a disposable PostgreSQL database.
BEGIN;
DO $test$
DECLARE
  v_company text := 'chunk-test-' || gen_random_uuid()::text;
  v_repo uuid := gen_random_uuid();
  v_run uuid := gen_random_uuid();
  v_snapshot uuid := gen_random_uuid();
  v_count integer;
BEGIN
  INSERT INTO public.companies (id, name) VALUES (v_company, 'Source chunk test');
  INSERT INTO public.repositories (id, company_id, full_name, baseline_status, baseline_run_id, baseline_lease_expires_at)
  VALUES (v_repo, v_company, 'chunk-test/repository', 'indexing', v_run, now() + interval '10 minutes');
  PERFORM public.create_repository_snapshot(v_repo, v_company, v_run, repeat('a', 40), v_snapshot);
  INSERT INTO public.codebase_files (id, repository_id, file_path, snapshot_id)
  VALUES (gen_random_uuid(), v_repo, 'src/main.py', v_snapshot);

  INSERT INTO public.source_code_chunks (
    repository_id, snapshot_id, company_id, chunk_id, file_path, content,
    content_hash, source_content_hash, source_revision, start_line, end_line,
    start_byte, end_byte, chunk_index, chunker_version
  ) VALUES (
    v_repo, v_snapshot, v_company, repeat('b', 64), 'src/main.py', 'def main(): return 1',
    repeat('c', 64), repeat('d', 64), repeat('a', 40), 1, 1, 0, 20, 0, 'line-window-v1'
  );

  -- Stale source revision must be rejected by the snapshot trigger.
  BEGIN
    INSERT INTO public.source_code_chunks (
      repository_id, snapshot_id, company_id, chunk_id, file_path, content,
      content_hash, source_content_hash, source_revision, start_line, end_line,
      start_byte, end_byte, chunk_index, chunker_version
    ) VALUES (
      v_repo, v_snapshot, v_company, repeat('e', 64), 'src/main.py', 'stale',
      repeat('c', 64), repeat('d', 64), repeat('f', 40), 1, 1, 0, 5, 1, 'line-window-v1'
    );
    RAISE EXCEPTION 'stale chunk unexpectedly persisted';
  EXCEPTION WHEN check_violation THEN NULL;
  END;

  BEGIN
    UPDATE public.repository_snapshots SET status = 'published', source_chunk_count = 0
    WHERE id = v_snapshot;
    RAISE EXCEPTION 'snapshot published with incorrect source chunk count';
  EXCEPTION WHEN check_violation THEN NULL;
  END;

  IF public.refresh_snapshot_source_chunk_validation(v_snapshot, v_company) <> 1 THEN
    RAISE EXCEPTION 'source chunk validation count mismatch';
  END IF;
  UPDATE public.repository_snapshots SET status = 'published' WHERE id = v_snapshot;
  RAISE NOTICE 'source chunk persistence integration checks passed';
END
$test$;
ROLLBACK;
