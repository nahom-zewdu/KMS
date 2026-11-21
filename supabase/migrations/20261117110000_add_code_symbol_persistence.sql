-- Revision-pinned, tenant-scoped symbol declarations extracted from immutable snapshots.
BEGIN;

CREATE TABLE IF NOT EXISTS public.code_symbols (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  repository_id uuid NOT NULL,
  snapshot_id uuid NOT NULL,
  company_id text NOT NULL,
  symbol_id text NOT NULL CHECK (symbol_id ~ '^[0-9a-f]{64}$'),
  file_path text NOT NULL CHECK (btrim(file_path) <> ''),
  language text NOT NULL CHECK (language IN ('Python', 'Go', 'JavaScript', 'TypeScript', 'TSX')),
  name text NOT NULL CHECK (btrim(name) <> ''),
  qualified_name text NOT NULL CHECK (btrim(qualified_name) <> ''),
  kind text NOT NULL CHECK (kind IN ('function', 'method', 'class', 'interface', 'struct', 'type', 'enum')),
  start_line integer NOT NULL CHECK (start_line > 0),
  end_line integer NOT NULL CHECK (end_line >= start_line),
  start_byte integer NOT NULL CHECK (start_byte >= 0),
  end_byte integer NOT NULL CHECK (end_byte > start_byte),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  source_revision text NOT NULL CHECK (btrim(source_revision) <> ''),
  extractor_version text NOT NULL CHECK (btrim(extractor_version) <> ''),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT code_symbols_snapshot_symbol_key UNIQUE (snapshot_id, symbol_id),
  CONSTRAINT code_symbols_snapshot_span_key UNIQUE
    (snapshot_id, file_path, start_byte, end_byte, qualified_name, kind),
  CONSTRAINT code_symbols_snapshot_repository_fk
    FOREIGN KEY (repository_id, snapshot_id)
    REFERENCES public.repository_snapshots(repository_id, id)
    ON DELETE CASCADE,
  CONSTRAINT code_symbols_snapshot_company_fk
    FOREIGN KEY (snapshot_id, company_id)
    REFERENCES public.repository_snapshots(id, company_id)
    ON DELETE CASCADE,
  CONSTRAINT code_symbols_snapshot_file_fk
    FOREIGN KEY (repository_id, file_path, snapshot_id)
    REFERENCES public.codebase_files(repository_id, file_path, snapshot_id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_code_symbols_snapshot_path
  ON public.code_symbols(snapshot_id, file_path, start_byte);
CREATE INDEX IF NOT EXISTS idx_code_symbols_snapshot_qualified_name
  ON public.code_symbols(snapshot_id, qualified_name);
CREATE INDEX IF NOT EXISTS idx_code_symbols_repository_revision
  ON public.code_symbols(repository_id, source_revision);

ALTER TABLE public.repository_snapshots
  ADD COLUMN IF NOT EXISTS symbol_count integer NOT NULL DEFAULT 0
    CHECK (symbol_count >= 0),
  ADD COLUMN IF NOT EXISTS symbol_validation jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE OR REPLACE FUNCTION public.validate_code_symbol_snapshot()
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
    RAISE EXCEPTION 'symbols can only be written to a building snapshot in the same tenant'
      USING ERRCODE = '42501';
  END IF;

  IF NEW.source_revision IS DISTINCT FROM v_revision THEN
    RAISE EXCEPTION 'symbol source revision does not match its repository snapshot'
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS code_symbols_validate_snapshot ON public.code_symbols;
CREATE TRIGGER code_symbols_validate_snapshot
  BEFORE INSERT OR UPDATE ON public.code_symbols
  FOR EACH ROW EXECUTE FUNCTION public.validate_code_symbol_snapshot();

CREATE OR REPLACE FUNCTION public.validate_snapshot_symbol_count()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actual integer;
BEGIN
  IF NEW.status = 'published' AND OLD.status IS DISTINCT FROM 'published' THEN
    SELECT count(*) INTO v_actual
    FROM public.code_symbols
    WHERE snapshot_id = NEW.id;

    IF v_actual <> NEW.symbol_count THEN
      RAISE EXCEPTION 'snapshot symbol count mismatch: stored %, actual %',
        NEW.symbol_count, v_actual
        USING ERRCODE = '23514';
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS repository_snapshot_symbol_count_check ON public.repository_snapshots;
CREATE TRIGGER repository_snapshot_symbol_count_check
  BEFORE UPDATE OF status ON public.repository_snapshots
  FOR EACH ROW EXECUTE FUNCTION public.validate_snapshot_symbol_count();

ALTER TABLE public.code_symbols ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.code_symbols FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.code_symbols TO service_role;
REVOKE ALL ON FUNCTION public.validate_code_symbol_snapshot() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.validate_snapshot_symbol_count() FROM PUBLIC, anon, authenticated;

COMMIT;
