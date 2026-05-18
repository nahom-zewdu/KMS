-- schema/graph_traverser_rpc.sql
-- supabase/functions/search_edges_by_entity.sql
-- Graph Traverser RPC: search edges by entity name + relation types filter 
-- Returns edges where either source or target entity name matches the search term
-- and edge type is in the provided relation types (if any).
-- Limits results to top 10 matches.

create or replace function public.search_edges_by_entity(search_term text, relation_types text[])
returns table (
    id uuid,
    source_name text,
    target_name text,
    type text,
    confidence double precision
)
language sql
as $$
    select 
        e.id,
        s.name as source_name,
        t.name as target_name,
        e.type,
        coalesce((e.metadata->>'confidence')::float, 0.9) as confidence
    from edges e
    join entities s on e.source_id = s.id
    join entities t on e.target_id = t.id
    where 
        lower(s.name) like '%' || lower(search_term) || '%'
        or lower(t.name) like '%' || lower(search_term) || '%'
        and (cardinality(relation_types) = 0 or e.type = any(relation_types))
    limit 10;
$$;