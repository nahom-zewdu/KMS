-- Tighten lease RPC validation and explicitly restrict execution to workers.
CREATE OR REPLACE FUNCTION public.claim_repository_baseline(
  p_full_name text, p_company_id text, p_source_revision text,
  p_run_id uuid, p_lease_seconds integer DEFAULT 180
)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path = public
AS $$
DECLARE repo_row public.repositories%ROWTYPE;
BEGIN
  IF p_full_name IS NULL OR btrim(p_full_name) = ''
     OR p_company_id IS NULL OR btrim(p_company_id) = ''
     OR lower(btrim(p_company_id)) = 'default'
     OR p_source_revision IS NULL OR btrim(p_source_revision) = ''
     OR p_run_id IS NULL OR p_lease_seconds IS NULL
     OR p_lease_seconds < 30 OR p_lease_seconds > 3600 THEN
    RAISE EXCEPTION 'valid repository, company, revision, run id, and lease duration are required';
  END IF;
  SELECT * INTO repo_row FROM public.repositories
  WHERE full_name = p_full_name AND company_id = p_company_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'repository not found for company'; END IF;
  IF repo_row.baseline_status = 'ready'
     AND repo_row.baseline_revision = p_source_revision THEN RETURN 'ready'; END IF;
  IF repo_row.baseline_status = 'indexing'
     AND repo_row.baseline_lease_expires_at > now() THEN RETURN 'busy'; END IF;
  UPDATE public.repositories
  SET baseline_status='indexing', baseline_run_id=p_run_id,
      baseline_lease_expires_at=now()+make_interval(secs=>p_lease_seconds),
      baseline_started_at=now(), baseline_error=NULL
  WHERE id=repo_row.id;
  RETURN 'claimed';
END;
$$;

CREATE OR REPLACE FUNCTION public.renew_repository_baseline_lease(
  p_full_name text, p_company_id text, p_run_id uuid,
  p_lease_seconds integer DEFAULT 180
)
RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER SET search_path = public
AS $$
DECLARE affected integer;
BEGIN
  IF p_lease_seconds IS NULL OR p_lease_seconds < 30 OR p_lease_seconds > 3600
  THEN RAISE EXCEPTION 'lease duration must be between 30 and 3600 seconds'; END IF;
  UPDATE public.repositories
  SET baseline_lease_expires_at=now()+make_interval(secs=>p_lease_seconds)
  WHERE full_name=p_full_name AND company_id=p_company_id
    AND baseline_status='indexing' AND baseline_run_id=p_run_id
    AND baseline_lease_expires_at>now();
  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected=1;
END;
$$;

CREATE OR REPLACE FUNCTION public.complete_repository_baseline(
  p_full_name text, p_company_id text, p_run_id uuid,
  p_source_revision text, p_file_count integer, p_completed_at timestamptz
)
RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER SET search_path = public
AS $$
DECLARE affected integer;
BEGIN
  IF p_source_revision IS NULL OR btrim(p_source_revision)=''
     OR p_file_count IS NULL OR p_file_count<0 OR p_completed_at IS NULL
  THEN RAISE EXCEPTION 'valid revision, file count, and completion timestamp are required'; END IF;
  UPDATE public.repositories
  SET baseline_status='ready', baseline_revision=p_source_revision,
      baseline_file_count=p_file_count, baseline_completed_at=p_completed_at,
      baseline_error=NULL, baseline_run_id=NULL, baseline_lease_expires_at=NULL,
      last_synced_at=p_completed_at
  WHERE full_name=p_full_name AND company_id=p_company_id
    AND baseline_status='indexing' AND baseline_run_id=p_run_id
    AND baseline_lease_expires_at>now();
  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected=1;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_repository_baseline(
  p_full_name text, p_company_id text, p_run_id uuid, p_error text
)
RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER SET search_path = public
AS $$
DECLARE affected integer;
BEGIN
  UPDATE public.repositories
  SET baseline_status='failed',
      baseline_error=COALESCE(NULLIF(left(p_error,2000),''),'Baseline indexing failed'),
      baseline_run_id=NULL, baseline_lease_expires_at=NULL
  WHERE full_name=p_full_name AND company_id=p_company_id
    AND baseline_status='indexing' AND baseline_run_id=p_run_id;
  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected=1;
END;
$$;

REVOKE ALL ON FUNCTION public.claim_repository_baseline(text,text,text,uuid,integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.renew_repository_baseline_lease(text,text,uuid,integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.complete_repository_baseline(text,text,uuid,text,integer,timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fail_repository_baseline(text,text,uuid,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_repository_baseline(text,text,text,uuid,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.renew_repository_baseline_lease(text,text,uuid,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.complete_repository_baseline(text,text,uuid,text,integer,timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.fail_repository_baseline(text,text,uuid,text) TO service_role;
