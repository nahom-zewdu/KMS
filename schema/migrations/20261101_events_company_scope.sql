-- Events contain raw provider payloads and are tenant-associated. Populate only
-- from an unambiguous linked raw_data row; unresolved history requires explicit
-- operator mapping before this migration can succeed.
BEGIN;

ALTER TABLE public.events
  ADD COLUMN IF NOT EXISTS company_id text;

DO $$
BEGIN
  IF to_regclass('public.companies') IS NULL
     OR to_regclass('public.raw_data') IS NULL THEN
    RAISE EXCEPTION 'companies and raw_data must exist before scoping events';
  END IF;
END;
$$;

UPDATE public.events AS event
SET company_id = mapping.company_id
FROM (
  SELECT event_id, min(company_id) AS company_id
  FROM public.raw_data
  WHERE event_id IS NOT NULL
    AND company_id IS NOT NULL
    AND btrim(company_id) <> ''
    AND lower(btrim(company_id)) <> 'default'
  GROUP BY event_id
  HAVING count(DISTINCT company_id) = 1
) AS mapping
WHERE event.id = mapping.event_id
  AND event.company_id IS NULL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM public.events AS event
    WHERE event.company_id IS NULL
       OR btrim(event.company_id) = ''
       OR lower(btrim(event.company_id)) = 'default'
  ) THEN
    RAISE EXCEPTION 'events contain unmapped tenant ownership; explicitly map every event.company_id and retry';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.events AS event
    LEFT JOIN public.companies AS company ON company.id = event.company_id
    WHERE company.id IS NULL
  ) THEN
    RAISE EXCEPTION 'events contain company_id values without a matching company';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.events AS event
    JOIN public.raw_data AS raw ON raw.event_id = event.id
    WHERE raw.company_id IS DISTINCT FROM event.company_id
  ) THEN
    RAISE EXCEPTION 'event and linked raw_data company ownership conflicts';
  END IF;
END;
$$;

ALTER TABLE public.events
  ALTER COLUMN company_id SET NOT NULL;

DO $$
DECLARE
  company_attnum smallint;
  company_id_attnum smallint;
  constraint_row record;
BEGIN
  SELECT attnum INTO company_attnum
  FROM pg_attribute
  WHERE attrelid = 'public.events'::regclass
    AND attname = 'company_id'
    AND NOT attisdropped;

  SELECT attnum INTO company_id_attnum
  FROM pg_attribute
  WHERE attrelid = 'public.companies'::regclass
    AND attname = 'id'
    AND NOT attisdropped;

  IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.events'::regclass
      AND conname = 'events_company_id_fkey'
      AND NOT (
        contype = 'f'
        AND confrelid = 'public.companies'::regclass
        AND conkey = ARRAY[company_attnum]::smallint[]
        AND confkey = ARRAY[company_id_attnum]::smallint[]
      )
  ) THEN
    RAISE EXCEPTION 'events_company_id_fkey exists with an unexpected definition';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.events'::regclass
      AND contype = 'f'
      AND confrelid = 'public.companies'::regclass
      AND conkey = ARRAY[company_attnum]::smallint[]
      AND confkey = ARRAY[company_id_attnum]::smallint[]
  ) THEN
    ALTER TABLE public.events
      ADD CONSTRAINT events_company_id_fkey
      FOREIGN KEY (company_id) REFERENCES public.companies(id) NOT VALID;
  END IF;

  FOR constraint_row IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'public.events'::regclass
      AND contype = 'f'
      AND confrelid = 'public.companies'::regclass
      AND conkey = ARRAY[company_attnum]::smallint[]
      AND confkey = ARRAY[company_id_attnum]::smallint[]
      AND NOT convalidated
  LOOP
    EXECUTE format('ALTER TABLE public.events VALIDATE CONSTRAINT %I', constraint_row.conname);
  END LOOP;

  IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.events'::regclass
      AND conname = 'events_company_id_not_default'
      AND NOT (
        contype = 'c'
        AND pg_get_constraintdef(oid) LIKE '%lower(btrim(company_id)) <> ''default''%'
      )
  ) THEN
    RAISE EXCEPTION 'events_company_id_not_default exists with an unexpected definition';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.events'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%lower(btrim(company_id)) <> ''default''%'
  ) THEN
    ALTER TABLE public.events
      ADD CONSTRAINT events_company_id_not_default
      CHECK (
        company_id IS NOT NULL
        AND btrim(company_id) <> ''
        AND lower(btrim(company_id)) <> 'default'
      ) NOT VALID;
  END IF;
END;
$$;

ALTER TABLE public.events
  VALIDATE CONSTRAINT events_company_id_not_default;

-- Preserve globally unique delivery IDs: duplicate deliveries must not be
-- accepted even if their tenant differs.
DO $$
DECLARE
  delivery_attnum smallint;
BEGIN
  SELECT attnum INTO delivery_attnum
  FROM pg_attribute
  WHERE attrelid = 'public.events'::regclass
    AND attname = 'delivery_id'
    AND NOT attisdropped;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_index
    WHERE indrelid = 'public.events'::regclass
      AND indisunique
      AND indisvalid
      AND indpred IS NULL
      AND indkey = ARRAY[delivery_attnum]::smallint[]
  ) THEN
    IF EXISTS (
      SELECT 1
      FROM public.events
      WHERE delivery_id IS NOT NULL
      GROUP BY delivery_id
      HAVING count(*) > 1
    ) THEN
      RAISE EXCEPTION 'duplicate delivery_id values exist; reconcile before enforcing global idempotency';
    END IF;

    IF EXISTS (
      SELECT 1 FROM pg_class
      WHERE oid = to_regclass('public.events_delivery_id_uidx')
    ) THEN
      RAISE EXCEPTION 'events_delivery_id_uidx exists but is not the expected unique delivery index';
    END IF;

    CREATE UNIQUE INDEX events_delivery_id_uidx
      ON public.events (delivery_id);
  END IF;
END;
$$;

COMMIT;
