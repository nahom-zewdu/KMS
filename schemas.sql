-- schema.sql
-- Purpose: Resets the Supabase database for KnowSphere by dropping all existing tables,
-- then recreates a clean public schema with tables for GitHub/Slack event ingestion,
-- knowledge graph storage, and contribution metrics.
-- Maintains Supabase compatibility (keeps grants for anon, authenticated, service_role).

-- ============================================================
--  SAFE RESET SECTION
-- ============================================================

-- Drop all user-defined tables (but not the schema itself)
DO $$
DECLARE
    r RECORD;
BEGIN
    -- Drop all tables in the 'public' schema
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public')
    LOOP
        EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;
END $$;

-- (Optional) drop custom types or materialized views if you had any
-- DO similar block for them if needed.

-- ============================================================
--  TABLE DEFINITIONS
-- ============================================================

-- Events table: Stores raw GitHub/Slack payloads
CREATE TABLE public.events (
    id UUID PRIMARY KEY,
    source TEXT CHECK (source IN ('slack', 'github')) NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    delivery_id TEXT UNIQUE,
    processed BOOLEAN DEFAULT FALSE,
    truncated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE public.events IS 'Stores raw event payloads from GitHub/Slack webhooks for auditability and processing.';
CREATE INDEX idx_events_source ON public.events (source);
CREATE INDEX idx_events_delivery_id ON public.events (delivery_id);
COMMENT ON INDEX idx_events_source IS 'Index on source column for efficient filtering by slack/github.';
COMMENT ON INDEX idx_events_delivery_id IS 'Index on delivery_id for fast idempotency checks.';


-- Raw Data table: summarized event content linked to raw payloads
CREATE TABLE public.raw_data (
    id UUID PRIMARY KEY,
    source TEXT CHECK (source IN ('slack', 'github')) NOT NULL,
    content TEXT NOT NULL,
    record_id TEXT NOT NULL,
    event_id UUID REFERENCES public.events(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_raw_data_record_id ON public.raw_data (record_id);
COMMENT ON TABLE public.raw_data IS 'Stores summarized event content from Slack/GitHub, linked to raw payloads in events.';
COMMENT ON INDEX idx_raw_data_record_id IS 'Index on record_id for fast lookup of summarized content.';


-- Entities table: knowledge graph nodes
CREATE TABLE public.entities (
    id UUID PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    metadata JSONB,
    active BOOLEAN DEFAULT TRUE,
    search_vector TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', name || ' ' || coalesce(metadata->>'description', ''))
    ) STORED,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX entities_search_idx ON public.entities USING GIN(search_vector);
COMMENT ON TABLE public.entities IS 'Stores knowledge graph entities (PERSON, PROJECT, TICKET) extracted from events.';
COMMENT ON INDEX entities_search_idx IS 'GIN index for full-text search on entity names/metadata.';


-- Edges: relationships between entities
CREATE TABLE public.edges (
    id UUID PRIMARY KEY,
    source_id UUID REFERENCES public.entities(id) NOT NULL,
    target_id UUID REFERENCES public.entities(id) NOT NULL,
    type TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE public.edges IS 'Stores relationships between entities (e.g., PERSON authored PROJECT).';


-- Contributions: metrics per PERSON/PROJECT pair
CREATE TABLE public.contributions (
    id UUID PRIMARY KEY,
    person_name TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    commit_count INTEGER DEFAULT 0,
    pr_count INTEGER DEFAULT 0,
    issue_count INTEGER DEFAULT 0,
    bus_factor FLOAT DEFAULT 0.0 CHECK (bus_factor >= 0 AND bus_factor <= 1),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(person_name, repo_name)
);
CREATE INDEX idx_contributions_repo_name ON public.contributions (repo_name);
COMMENT ON TABLE public.contributions IS 'Tracks contribution metrics per person per repository.';
COMMENT ON INDEX idx_contributions_repo_name IS 'Index for fast metrics queries by repository.';


-- Pull Requests
CREATE TABLE public.pull_requests (
    id UUID PRIMARY KEY,
    event_id UUID REFERENCES public.events(id),
    pr_number INTEGER NOT NULL,
    repo_name TEXT NOT NULL,
    title TEXT,
    body TEXT,
    assignee_id UUID REFERENCES public.entities(id),
    reviewers JSONB,
    labels JSONB,
    commits_count INTEGER,
    merged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(pr_number, repo_name)
);
CREATE INDEX idx_pull_requests_repo_name ON public.pull_requests (repo_name);
COMMENT ON TABLE public.pull_requests IS 'Stores detailed GitHub pull request data, linked to events.';


-- Issues
CREATE TABLE public.issues (
    id UUID PRIMARY KEY,
    event_id UUID REFERENCES public.events(id),
    issue_number INTEGER NOT NULL,
    repo_name TEXT NOT NULL,
    title TEXT,
    body TEXT,
    assignee_id UUID REFERENCES public.entities(id),
    labels JSONB,
    state TEXT CHECK (state IN ('open', 'closed')) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(issue_number, repo_name)
);
CREATE INDEX idx_issues_repo_name ON public.issues (repo_name);
COMMENT ON TABLE public.issues IS 'Stores detailed GitHub issue data, linked to events.';


-- ============================================================
--  GRANT PERMISSIONS (SUPABASE COMPATIBLE)
-- ============================================================

GRANT ALL ON SCHEMA public TO postgres, anon, authenticated, service_role;

-- Grant existing tables
GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres, anon, authenticated, service_role;

-- Ensure future tables also get same privileges
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT ALL ON TABLES TO postgres, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT ALL ON SEQUENCES TO postgres, anon, authenticated, service_role;

COMMENT ON SCHEMA public IS 'Public schema for KnowSphere, containing event ingestion, knowledge graph, and metrics tables.';
