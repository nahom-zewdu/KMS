-- Durable source passages for lexical retrieval, pinned to immutable snapshots.
BEGIN;

CREATE TABLE IF NOT EXISTS public.source_code_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  repository_id uuid NOT NULL,
  snapshot_id uuid NOT NULL,
  company_id text NOT NULL,
  chunk_id text NOT NULL CHECK (chunk_id ~ '^[0-9a-f]{64}$'),
  file_path text NOT NULL CHECK (btrim(file_path) <> ''),
  content text NOT NULL CHECK (btrim(content) <> ''),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  source_content_hash text NOT NULL CHECK (source_content_hash ~ '^[0-9a-f]{64}$'),
  source_revision text NOT NULL CHECK (btrim(source_revision) <> ''),
  start_line integer NOT NULL CHECK (start_line > 0),
  end_line integer NOT NULL CHECK (end_line >= start_line),
  start_byte integer NOT NULL CHECK (start_byte >= 0),
  end_byte integer NOT NULL CHECK (end_byte > start_byte),
  chunk_index integer NOT NULL CHECK (chunk_index >= 0),
  chunker_version text NOT NULL CHECK (btrim(chunker_version) <> ''),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT source_code_chunks_snapshot_identity_key UNIQUE (snapshot_id, chunk_id),
  CONSTRAINT source_code_chunks_snapshot_repository_fk
    FOREIGN KEY (repository_id, snapshot_id)
    REFERENCES public.repository_snapshots(repository_id, id) ON DELETE CASCADE,
  CONSTRAINT source_code_chunks_snapshot_company_fk
    FOREIGN KEY (snapshot_id, company_id)
    REFERENCES public.repository_snapshots(id, company_id) ON DELETE CASCADE,
  CONSTRAINT source_code_chunks_snapshot_file_fk
    FOREIGN KEY (repository_id, file_path, snapshot_id)
    REFERENCES public.codebase_files(repository_id, file_path, snapshot_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_source_code_chunks_snapshot_path
  ON public.source_code_chunks(snapshot_id, file_path, start_byte);
CREATE INDEX IF NOT EXISTS idx_source_code_chunks_snapshot_company
  ON public.source_code_chunks(company_id, repository_id, snapshot_id);

ALTER TABLE public.repository_snapshots
  ADD COLUMN IF NOT EXISTS source_chunk_count integer NOT NULL DEFAULT 0
    CHECK (source_chunk_count >= 0),
  ADD COLUMN IF NOT EXISTS source_chunk_validation jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE OR REPLACE FUNCTION public.validate_source_code_chunk_snapshot()
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
    RAISE EXCEPTION 'source chunks can only be written to a building snapshot in the same tenant'
      USING ERRCODE = '42501';
  END IF;

  IF NEW.source_revision IS DISTINCT FROM v_revision THEN
    RAISE EXCEPTION 'source chunk revision does not match its repository snapshot'
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS source_code_chunks_validate_snapshot ON public.source_code_chunks;
CREATE TRIGGER source_code_chunks_validate_snapshot
  BEFORE INSERT OR UPDATE ON public.source_code_chunks
  FOR EACH ROW EXECUTE FUNCTION public.validate_source_code_chunk_snapshot();

CREATE OR REPLACE FUNCTION public.validate_snapshot_source_chunk_count()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actual integer;
BEGIN
  IF NEW.status = 'published' AND OLD.status IS DISTINCT FROM 'published' THEN
    SELECT count(*) INTO v_actual
    FROM public.source_code_chunks
    WHERE snapshot_id = NEW.id;

    IF v_actual <> NEW.source_chunk_count THEN
      RAISE EXCEPTION 'snapshot source chunk count mismatch: stored %, actual %',
        NEW.source_chunk_count, v_actual
        USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS repository_snapshot_source_chunk_count_check
  ON public.repository_snapshots;
CREATE TRIGGER repository_snapshot_source_chunk_count_check
  BEFORE UPDATE OF status ON public.repository_snapshots
  FOR EACH ROW EXECUTE FUNCTION public.validate_snapshot_source_chunk_count();

CREATE OR REPLACE FUNCTION public.refresh_snapshot_source_chunk_validation(
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
    RAISE EXCEPTION 'source chunk metrics can only be refreshed for a building snapshot'
      USING ERRCODE = '42501';
  END IF;

  SELECT count(*) INTO v_actual
  FROM public.source_code_chunks
  WHERE snapshot_id = p_snapshot_id AND company_id = p_company_id;

  UPDATE public.repository_snapshots
  SET source_chunk_count = v_actual,
      source_chunk_validation = jsonb_build_object(
        'source_chunks_persisted', v_actual,
        'validated_at', now()
      )
  WHERE id = p_snapshot_id AND company_id = p_company_id;

  RETURN v_actual;
END;
$$;

REVOKE ALL ON FUNCTION public.refresh_snapshot_source_chunk_validation(uuid,text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.refresh_snapshot_source_chunk_validation(uuid,text)
  TO service_role;

ALTER TABLE public.source_code_chunks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.source_code_chunks FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.source_code_chunks TO service_role;
REVOKE ALL ON FUNCTION public.validate_source_code_chunk_snapshot()
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.validate_snapshot_source_chunk_count()
  FROM PUBLIC, anon, authenticated;

COMMIT;
