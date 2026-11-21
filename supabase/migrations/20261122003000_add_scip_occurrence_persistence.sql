-- Revision-pinned semantic definitions and references produced by SCIP.
-- Kept separate from code_symbols, which stores syntax-derived declarations.
BEGIN;

CREATE TABLE IF NOT EXISTS public.code_symbol_occurrences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  repository_id uuid NOT NULL,
  snapshot_id uuid NOT NULL,
  company_id text NOT NULL,
  occurrence_id text NOT NULL CHECK (occurrence_id ~ '^[0-9a-f]{64}$'),
  file_path text NOT NULL CHECK (btrim(file_path) <> ''),
  symbol text NOT NULL CHECK (btrim(symbol) <> ''),
  role text NOT NULL CHECK (role IN ('definition', 'reference', 'occurrence')),
  symbol_roles integer NOT NULL CHECK (symbol_roles >= 0),
  start_line integer NOT NULL CHECK (start_line > 0),
  end_line integer NOT NULL CHECK (end_line >= start_line),
  start_byte integer NOT NULL CHECK (start_byte >= 0),
  end_byte integer NOT NULL CHECK (end_byte >= start_byte),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  source_revision text NOT NULL CHECK (btrim(source_revision) <> ''),
  indexer_name text NOT NULL CHECK (btrim(indexer_name) <> ''),
  indexer_version text NOT NULL CHECK (btrim(indexer_version) <> ''),
  protocol_version integer NOT NULL CHECK (protocol_version >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT code_symbol_occurrences_snapshot_identity_key
    UNIQUE (snapshot_id, occurrence_id),
  CONSTRAINT code_symbol_occurrences_snapshot_repository_fk
    FOREIGN KEY (repository_id, snapshot_id)
    REFERENCES public.repository_snapshots(repository_id, id)
    ON DELETE CASCADE,
  CONSTRAINT code_symbol_occurrences_snapshot_company_fk
    FOREIGN KEY (snapshot_id, company_id)
    REFERENCES public.repository_snapshots(id, company_id)
    ON DELETE CASCADE,
  CONSTRAINT code_symbol_occurrences_snapshot_file_fk
    FOREIGN KEY (repository_id, file_path, snapshot_id)
    REFERENCES public.codebase_files(repository_id, file_path, snapshot_id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_code_symbol_occurrences_snapshot_symbol
  ON public.code_symbol_occurrences(snapshot_id, symbol, role);
CREATE INDEX IF NOT EXISTS idx_code_symbol_occurrences_snapshot_file
  ON public.code_symbol_occurrences(snapshot_id, file_path, start_byte);
CREATE INDEX IF NOT EXISTS idx_code_symbol_occurrences_snapshot_role
  ON public.code_symbol_occurrences(snapshot_id, symbol, role);

ALTER TABLE public.repository_snapshots
  ADD COLUMN IF NOT EXISTS occurrence_count integer NOT NULL DEFAULT 0
    CHECK (occurrence_count >= 0),
  ADD COLUMN IF NOT EXISTS occurrence_validation jsonb NOT NULL DEFAULT '{}'::jsonb;

-- Locking the snapshot row serializes occurrence writes with publication.
-- The composite FKs independently enforce repository, tenant, and file ownership.
CREATE OR REPLACE FUNCTION public.validate_code_symbol_occurrence_snapshot()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_revision text;
  v_status text;
BEGIN
  SELECT source_revision, status
  INTO v_revision, v_status
  FROM public.repository_snapshots
  WHERE id = NEW.snapshot_id
    AND repository_id = NEW.repository_id
    AND company_id = NEW.company_id
  FOR UPDATE;

  IF NOT FOUND OR v_status <> 'building' THEN
    RAISE EXCEPTION 'semantic occurrences can only be written to a building snapshot in the same tenant'
      USING ERRCODE = '42501';
  END IF;

  IF NEW.source_revision IS DISTINCT FROM v_revision THEN
    RAISE EXCEPTION 'occurrence source revision does not match its repository snapshot'
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS code_symbol_occurrences_validate_snapshot
  ON public.code_symbol_occurrences;
CREATE TRIGGER code_symbol_occurrences_validate_snapshot
  BEFORE INSERT OR UPDATE ON public.code_symbol_occurrences
  FOR EACH ROW EXECUTE FUNCTION public.validate_code_symbol_occurrence_snapshot();

CREATE OR REPLACE FUNCTION public.validate_snapshot_occurrence_count()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actual integer;
BEGIN
  IF NEW.status = 'published' AND OLD.status IS DISTINCT FROM 'published' THEN
    SELECT count(*) INTO v_actual
    FROM public.code_symbol_occurrences
    WHERE snapshot_id = NEW.id;

    IF v_actual <> NEW.occurrence_count THEN
      RAISE EXCEPTION 'snapshot occurrence count mismatch: stored %, actual %',
        NEW.occurrence_count, v_actual
        USING ERRCODE = '23514';
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS repository_snapshot_occurrence_count_check
  ON public.repository_snapshots;
CREATE TRIGGER repository_snapshot_occurrence_count_check
  BEFORE UPDATE OF status ON public.repository_snapshots
  FOR EACH ROW EXECUTE FUNCTION public.validate_snapshot_occurrence_count();

-- Recompute from persisted rows so multiple language indexers can contribute to
-- the same snapshot without overwriting one another's counts.
CREATE OR REPLACE FUNCTION public.refresh_snapshot_occurrence_validation(
  p_snapshot_id uuid,
  p_company_id text
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_status text;
  v_actual integer;
BEGIN
  SELECT status INTO v_status
  FROM public.repository_snapshots
  WHERE id = p_snapshot_id AND company_id = p_company_id
  FOR UPDATE;

  IF NOT FOUND OR v_status <> 'building' THEN
    RAISE EXCEPTION 'occurrence metrics can only be refreshed for a building snapshot'
      USING ERRCODE = '42501';
  END IF;

  SELECT count(*) INTO v_actual
  FROM public.code_symbol_occurrences
  WHERE snapshot_id = p_snapshot_id
    AND company_id = p_company_id;

  UPDATE public.repository_snapshots
  SET occurrence_count = v_actual,
      occurrence_validation = jsonb_build_object(
        'occurrences_persisted', v_actual,
        'validated_at', now()
      )
  WHERE id = p_snapshot_id AND company_id = p_company_id;

  RETURN v_actual;
END;
$$;

REVOKE ALL ON FUNCTION public.refresh_snapshot_occurrence_validation(uuid,text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.refresh_snapshot_occurrence_validation(uuid,text)
  TO service_role;

ALTER TABLE public.code_symbol_occurrences ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.code_symbol_occurrences FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.code_symbol_occurrences TO service_role;
REVOKE ALL ON FUNCTION public.validate_code_symbol_occurrence_snapshot()
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.validate_snapshot_occurrence_count()
  FROM PUBLIC, anon, authenticated;

COMMIT;
