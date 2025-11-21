-- supabase/functions/match_documents.sql
create or replace function public.match_documents(
  query_embedding vector(384),
  match_threshold float default 0.75,
  match_count int default 10
)
returns table (
  id uuid,
  record_id text,
  content text,
  source text,
  created_at timestamptz,
  similarity double precision
)
language plpgsql
as $$
begin
  return query
  select
    r.id,
    r.record_id,
    r.content,
    r.source,
    r.created_at,
    (1 - (r.embedding <=> query_embedding))::double precision as similarity
  from raw_data r
  where r.embedding is not null
    and (r.embedding <=> query_embedding) < (1 - match_threshold)
  order by r.embedding <=> query_embedding
  limit match_count;
end;
$$;

-- Grant access
grant execute on function public.match_documents(vector(384), float, int) to service_role;
