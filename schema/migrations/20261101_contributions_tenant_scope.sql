-- Scope contribution metrics to their owning company.
-- Historical rows are assigned only when repo_name maps to exactly one company.
-- Ambiguous, orphaned, or already inconsistent rows abort the transaction so an
-- operator can reconcile them explicitly before deployment.
BEGIN;

ALTER TABLE public.contributions
  ADD COLUMN IF NOT EXISTS company_id text;

DO $$
BEGIN
  IF to_regclass('public.repositories') IS NULL OR to_regclass('public.companies') IS NULL THEN
    RAISE EXCEPTION 'repositories and companies must exist before scoping contributions';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.contributions AS c
    LEFT JOIN public.repositories AS r ON r.full_name = c.repo_name
    WHERE c.company_id IS NULL
    GROUP BY c.id
    HAVING count(DISTINCT r.company_id) <> 1
  ) THEN
    RAISE EXCEPTION 'contribution rows have missing or ambiguous repository ownership; reconcile before migration';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.contributions AS c
    LEFT JOIN public.repositories AS r
      ON r.full_name = c.repo_name
     AND r.company_id = c.company_id
    WHERE c.company_id IS NOT NULL
      AND r.id IS NULL
  ) THEN
    RAISE EXCEPTION 'contribution company_id does not match repository ownership';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.contributions AS c
    LEFT JOIN public.repositories AS r ON r.full_name = c.repo_name
    WHERE lower(btrim(COALESCE(c.company_id, r.company_id, ''))) = 'default'
  ) THEN
    RAISE EXCEPTION 'default-company contribution rows are not eligible for tenant migration';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.repositories AS r
    LEFT JOIN public.companies AS c ON c.id = r.company_id
    WHERE c.id IS NULL
      AND EXISTS (
        SELECT 1 FROM public.contributions AS contribution
        WHERE contribution.repo_name = r.full_name
      )
  ) THEN
    RAISE EXCEPTION 'contribution repository references a missing company';
  END IF;
END;
$$;

UPDATE public.contributions AS c
SET company_id = r.company_id
FROM public.repositories AS r
WHERE c.company_id IS NULL
  AND r.full_name = c.repo_name;

ALTER TABLE public.contributions
  ALTER COLUMN company_id SET NOT NULL;

DO $$
DECLARE
  constraint_row record;
  company_attnum smallint;
BEGIN
  FOR constraint_row IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'public.contributions'::regclass
      AND contype = 'u'
      AND pg_get_constraintdef(oid) = 'UNIQUE (person_name, repo_name)'
  LOOP
    EXECUTE format('ALTER TABLE public.contributions DROP CONSTRAINT %I', constraint_row.conname);
  END LOOP;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.contributions'::regclass
      AND contype = 'u'
      AND pg_get_constraintdef(oid) = 'UNIQUE (company_id, person_name, repo_name)'
  ) THEN
    ALTER TABLE public.contributions
      ADD CONSTRAINT contributions_company_person_repo_key
      UNIQUE (company_id, person_name, repo_name);
  END IF;

  SELECT attnum INTO company_attnum
  FROM pg_attribute
  WHERE attrelid = 'public.contributions'::regclass
    AND attname = 'company_id'
    AND NOT attisdropped;

  IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.contributions'::regclass
      AND conname = 'contributions_company_id_fkey'
      AND NOT (
        contype = 'f'
        AND confrelid = 'public.companies'::regclass
        AND conkey = ARRAY[company_attnum]::smallint[]
        AND confkey = ARRAY[
          (
            SELECT attnum
            FROM pg_attribute
            WHERE attrelid = 'public.companies'::regclass
              AND attname = 'id'
              AND NOT attisdropped
          )
        ]::smallint[]
      )
  ) THEN
    RAISE EXCEPTION 'contributions_company_id_fkey exists with an unexpected definition';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.contributions'::regclass
      AND contype = 'f'
      AND confrelid = 'public.companies'::regclass
      AND conkey = ARRAY[company_attnum]::smallint[]
  ) THEN
    ALTER TABLE public.contributions
      ADD CONSTRAINT contributions_company_id_fkey
      FOREIGN KEY (company_id) REFERENCES public.companies(id) NOT VALID;
  END IF;
END;
$$;

DO $$
DECLARE
  constraint_row record;
  company_attnum smallint;
BEGIN
  SELECT attnum INTO company_attnum
  FROM pg_attribute
  WHERE attrelid = 'public.contributions'::regclass
    AND attname = 'company_id'
    AND NOT attisdropped;

  FOR constraint_row IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'public.contributions'::regclass
      AND contype = 'f'
      AND confrelid = 'public.companies'::regclass
      AND conkey = ARRAY[company_attnum]::smallint[]
  LOOP
    EXECUTE format('ALTER TABLE public.contributions VALIDATE CONSTRAINT %I', constraint_row.conname);
  END LOOP;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_contributions_company_repo
  ON public.contributions (company_id, repo_name);

COMMIT;
