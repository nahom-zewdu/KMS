BEGIN;

DO $$
BEGIN
  IF to_regclass('public.events') IS NULL
     OR to_regclass('public.raw_data') IS NULL
     OR to_regclass('public.companies') IS NULL THEN
    RAISE EXCEPTION 'events, raw_data, and companies must exist before creating the ingestion outbox';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.events
    WHERE company_id IS NULL OR btrim(company_id) = ''
       OR lower(btrim(company_id)) = 'default'
       OR delivery_id IS NULL OR btrim(delivery_id) = ''
  ) THEN
    RAISE EXCEPTION 'events must have real company IDs and delivery IDs before creating the ingestion outbox';
  END IF;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.events'::regclass
      AND conname = 'events_id_company_id_key'
      AND contype = 'u'
      AND conkey = ARRAY[
        (SELECT attnum FROM pg_attribute WHERE attrelid = 'public.events'::regclass AND attname = 'id'),
        (SELECT attnum FROM pg_attribute WHERE attrelid = 'public.events'::regclass AND attname = 'company_id')
      ]::smallint[]
  ) THEN
    ALTER TABLE public.events
      ADD CONSTRAINT events_id_company_id_key UNIQUE (id, company_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.events'::regclass
      AND conname = 'events_id_company_delivery_key'
      AND contype = 'u'
      AND conkey = ARRAY[
        (SELECT attnum FROM pg_attribute WHERE attrelid = 'public.events'::regclass AND attname = 'id'),
        (SELECT attnum FROM pg_attribute WHERE attrelid = 'public.events'::regclass AND attname = 'company_id'),
        (SELECT attnum FROM pg_attribute WHERE attrelid = 'public.events'::regclass AND attname = 'delivery_id')
      ]::smallint[]
  ) THEN
    ALTER TABLE public.events
      ADD CONSTRAINT events_id_company_delivery_key UNIQUE (id, company_id, delivery_id);
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.ingestion_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL,
  company_id text NOT NULL,
  delivery_id text NOT NULL UNIQUE,
  job_payload jsonb NOT NULL,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'publishing', 'published', 'dead_letter')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  available_at timestamptz NOT NULL DEFAULT now(),
  locked_by text,
  locked_until timestamptz,
  last_error text CHECK (last_error IS NULL OR length(last_error) <= 1000),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  CONSTRAINT ingestion_outbox_event_fkey
    FOREIGN KEY (event_id, company_id, delivery_id)
    REFERENCES public.events (id, company_id, delivery_id),
  CONSTRAINT ingestion_outbox_lock_state_check
    CHECK ((status = 'publishing') = (locked_by IS NOT NULL AND locked_until IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS ingestion_outbox_dispatch_idx
  ON public.ingestion_outbox (available_at, created_at)
  WHERE status IN ('pending', 'publishing');

ALTER TABLE public.ingestion_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ingestion_outbox FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.ingestion_outbox TO service_role;

CREATE OR REPLACE FUNCTION public.persist_ingestion_with_outbox(
  p_event jsonb,
  p_raw_data jsonb,
  p_job jsonb
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_event_id uuid;
  v_company_id text;
  v_delivery_id text;
  v_raw_record_id text;
  v_outbox_id uuid;
BEGIN
  v_event_id := nullif(p_event->>'id', '')::uuid;
  v_company_id := nullif(btrim(p_event->>'company_id'), '');
  v_delivery_id := nullif(btrim(p_event->>'delivery_id'), '');
  v_raw_record_id := nullif(btrim(p_raw_data->>'record_id'), '');

  IF v_event_id IS NULL OR v_company_id IS NULL
     OR lower(v_company_id) = 'default'
     OR v_delivery_id IS NULL OR v_raw_record_id IS NULL THEN
    RAISE EXCEPTION 'event, company, delivery, and raw record identities are required';
  END IF;
  IF p_raw_data->>'company_id' IS DISTINCT FROM v_company_id
     OR p_job->>'company_id' IS DISTINCT FROM v_company_id
     OR v_raw_record_id IS DISTINCT FROM v_delivery_id
     OR p_job->>'record_id' IS DISTINCT FROM v_delivery_id
     OR p_raw_data->>'source' IS DISTINCT FROM p_event->>'source'
     OR p_job->>'source' IS DISTINCT FROM p_event->>'source'
     OR p_job->>'event_type' IS DISTINCT FROM p_event->>'event_type'
     OR p_raw_data->>'content' IS DISTINCT FROM p_job->>'content' THEN
    RAISE EXCEPTION 'event, raw-data, and job tenant/delivery/source/content identities must match';
  END IF;

  INSERT INTO public.events
    (id, company_id, source, event_type, payload, delivery_id, processed, truncated, created_at)
  VALUES
    (v_event_id, v_company_id, p_event->>'source', p_event->>'event_type',
     p_event->'payload', v_delivery_id, coalesce((p_event->>'processed')::boolean, false),
     coalesce((p_event->>'truncated')::boolean, false),
     coalesce((p_event->>'created_at')::timestamptz, now()))
  ON CONFLICT (delivery_id) DO NOTHING;

  SELECT e.id INTO v_event_id
  FROM public.events AS e
  WHERE e.delivery_id = v_delivery_id
    AND e.company_id = v_company_id
  FOR UPDATE;
  IF v_event_id IS NULL THEN
    RAISE EXCEPTION 'delivery ID already belongs to a different company';
  END IF;

  INSERT INTO public.raw_data
    (id, company_id, source, content, record_id, event_id, created_at)
  VALUES
    (coalesce(nullif(p_raw_data->>'id', '')::uuid, gen_random_uuid()),
     v_company_id, p_raw_data->>'source', p_raw_data->>'content',
     v_raw_record_id, v_event_id, coalesce((p_raw_data->>'created_at')::timestamptz, now()))
  ON CONFLICT (record_id) DO NOTHING;

  IF NOT EXISTS (
    SELECT 1 FROM public.raw_data
    WHERE record_id = v_raw_record_id
      AND company_id = v_company_id
      AND event_id = v_event_id
  ) THEN
    RAISE EXCEPTION 'raw-data delivery identity already exists with different ownership';
  END IF;

  INSERT INTO public.ingestion_outbox
    (event_id, company_id, delivery_id, job_payload)
  VALUES (v_event_id, v_company_id, v_delivery_id, p_job)
  ON CONFLICT (delivery_id) DO NOTHING;

  SELECT id INTO v_outbox_id
  FROM public.ingestion_outbox
  WHERE delivery_id = v_delivery_id
    AND company_id = v_company_id
    AND event_id = v_event_id;
  IF v_outbox_id IS NULL THEN
    RAISE EXCEPTION 'delivery ID already has an outbox entry for different ownership';
  END IF;

  RETURN v_outbox_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.claim_ingestion_outbox(
  p_worker_id text,
  p_limit integer DEFAULT 25,
  p_lease_seconds integer DEFAULT 60
)
RETURNS SETOF public.ingestion_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF nullif(btrim(p_worker_id), '') IS NULL THEN
    RAISE EXCEPTION 'worker_id is required';
  END IF;
  RETURN QUERY
  WITH candidates AS (
    SELECT id
    FROM public.ingestion_outbox
    WHERE available_at <= now()
      AND (status = 'pending'
        OR (status = 'publishing' AND locked_until <= now()))
    ORDER BY available_at, created_at
    FOR UPDATE SKIP LOCKED
    LIMIT greatest(1, least(coalesce(p_limit, 25), 100))
  )
  UPDATE public.ingestion_outbox AS outbox
  SET status = 'publishing',
      attempt_count = attempt_count + 1,
      locked_by = p_worker_id,
      locked_until = now() + make_interval(secs => greatest(10, least(coalesce(p_lease_seconds, 60), 600))),
      updated_at = now()
  FROM candidates
  WHERE outbox.id = candidates.id
  RETURNING outbox.*;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_ingestion_outbox_published(p_id uuid, p_worker_id text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  changed integer;
BEGIN
  UPDATE public.ingestion_outbox
  SET status = 'published', published_at = now(), updated_at = now(),
      locked_by = NULL, locked_until = NULL, last_error = NULL
  WHERE id = p_id AND status = 'publishing' AND locked_by = p_worker_id;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_ingestion_outbox(
  p_id uuid,
  p_worker_id text,
  p_error text,
  p_max_attempts integer DEFAULT 12
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  next_status text;
BEGIN
  UPDATE public.ingestion_outbox
  SET status = CASE WHEN attempt_count >= greatest(1, least(p_max_attempts, 50))
                    THEN 'dead_letter' ELSE 'pending' END,
      available_at = CASE WHEN attempt_count >= greatest(1, least(p_max_attempts, 50))
                          THEN available_at
                          ELSE now() + make_interval(secs => least(300, power(2, least(attempt_count, 8))::integer)) END,
      last_error = left(coalesce(p_error, 'unknown dispatch error'), 1000),
      locked_by = NULL, locked_until = NULL, updated_at = now()
  WHERE id = p_id AND status = 'publishing' AND locked_by = p_worker_id
  RETURNING status INTO next_status;
  RETURN next_status;
END;
$$;

REVOKE ALL ON FUNCTION public.persist_ingestion_with_outbox(jsonb, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.claim_ingestion_outbox(text, integer, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.mark_ingestion_outbox_published(uuid, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fail_ingestion_outbox(uuid, text, text, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.persist_ingestion_with_outbox(jsonb, jsonb, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_ingestion_outbox(text, integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.mark_ingestion_outbox_published(uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fail_ingestion_outbox(uuid, text, text, integer) TO service_role;

COMMIT;
