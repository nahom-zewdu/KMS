-- schema/vector_search_rpc.sql
create or replace function public.match_documents(
  query_embedding vector(384),
  match_threshold float default 0.65,
  match_count int default 10,
  filter_company_id text default null
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
language plpgsql as $$
begin
  return query
  select
    r.id, r.record_id, r.content, r.source, r.created_at, r.company_id,
    (1 - (r.embedding <=> query_embedding))::double precision as similarity
  from raw_data r
  where r.embedding is not null
    and (filter_company_id is null or r.company_id = filter_company_id)
    and (r.embedding <=> query_embedding) < (1 - match_threshold)
  order by r.embedding <=> query_embedding
  limit match_count;
end;
$$;
