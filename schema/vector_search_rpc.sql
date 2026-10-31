-- schema/vector_search_rpc.sql
create or replace function public.match_documents(
  query_embedding vector(384),
  match_threshold float,
  match_count int,
  filter_company_id text
)
returns table (
  id uuid,
  record_id text,
  content text,
  source text,
  created_at timestamptz,
  company_id text,
  similarity double precision
)
language plpgsql
security invoker
set search_path = pg_catalog, public
as $$
begin
  IF filter_company_id IS NULL
     OR btrim(filter_company_id) = ''
     OR lower(btrim(filter_company_id)) = 'default' THEN
    RAISE EXCEPTION 'a real filter_company_id is required' USING ERRCODE = '22023';
  END IF;

  return query
  select
    r.id, r.record_id, r.content, r.source, r.created_at, r.company_id,
    (1 - (r.embedding <=> query_embedding))::double precision as similarity
  from raw_data r
  where r.embedding is not null
    and r.company_id = filter_company_id
    and (r.embedding <=> query_embedding) < (1 - match_threshold)
  order by r.embedding <=> query_embedding
  limit match_count;
end;
$$;

REVOKE ALL ON FUNCTION public.match_documents(vector, float, int, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.match_documents(vector, float, int, text) TO authenticated, service_role;
