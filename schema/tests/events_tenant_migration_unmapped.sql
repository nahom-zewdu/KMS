\set ON_ERROR_STOP on

CREATE TABLE public.companies (id text PRIMARY KEY);
CREATE TABLE public.events (
  id uuid PRIMARY KEY,
  source text NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  delivery_id text UNIQUE
);
CREATE TABLE public.raw_data (
  id uuid PRIMARY KEY,
  company_id text NOT NULL,
  event_id uuid
);
INSERT INTO public.companies VALUES ('company-a');
INSERT INTO public.events (id,source,event_type,payload,delivery_id)
VALUES ('72000000-0000-0000-0000-000000000001','github','push','{}','unmapped-delivery');

\set ON_ERROR_STOP off
\ir ../migrations/20261101_events_company_scope.sql
\set ON_ERROR_STOP on

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='events' AND column_name='company_id'
  ) THEN
    RAISE EXCEPTION 'failed tenant migration retained schema changes';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM public.events WHERE delivery_id='unmapped-delivery'
  ) THEN
    RAISE EXCEPTION 'failed tenant migration changed or deleted event data';
  END IF;
END;
$$;
