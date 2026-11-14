-- Additive schema migration for GitHub repository baseline indexing.
ALTER TABLE public.repositories
  ADD COLUMN IF NOT EXISTS baseline_status text NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS baseline_started_at timestamptz,
  ADD COLUMN IF NOT EXISTS baseline_completed_at timestamptz,
  ADD COLUMN IF NOT EXISTS baseline_error text,
  ADD COLUMN IF NOT EXISTS baseline_file_count integer,
  ADD COLUMN IF NOT EXISTS baseline_revision text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.repositories'::regclass
      AND conname = 'repositories_baseline_status_check'
  ) THEN
    ALTER TABLE public.repositories
      ADD CONSTRAINT repositories_baseline_status_check
      CHECK (baseline_status IN ('pending', 'indexing', 'ready', 'failed'));
  END IF;
END
$$;
