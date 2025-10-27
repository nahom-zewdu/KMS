-- schema.sql
-- Purpose: Resets the Supabase database for KnowSphere by dropping all existing schemas and tables,
-- then creates a new public schema with tables for GitHub/Slack event ingestion, knowledge graph storage,
-- and contribution metrics. Ensures compatibility with hybrid architecture, supports edge cases (unmerged PRs,
-- deleted repos, large payloads), and includes indexes/comments for maintainability and performance.

-- Drop all existing schemas and tables to start from a clean slate
DROP SCHEMA IF EXISTS public CASCADE;

-- Recreate the public schema
CREATE SCHEMA public;
COMMENT ON SCHEMA public IS 'Public schema for KnowSphere, containing tables for event ingestion, knowledge graph, and metrics.';

-- Events table: Stores raw GitHub/Slack payloads for auditability and processing
CREATE TABLE public.events (
    id UUID PRIMARY KEY,
    source TEXT CHECK (source IN ('slack', 'github')) NOT NULL,
    event_type TEXT NOT NULL, -- e.g., push, pull_request, app_mention
    payload JSONB NOT NULL, -- Raw JSON payload from webhook
    delivery_id TEXT UNIQUE, -- GitHub X-GitHub-Delivery or Slack-generated UUID
    processed BOOLEAN DEFAULT FALSE, -- Tracks if processed by hf_processor.py
    truncated BOOLEAN DEFAULT FALSE, -- Indicates if payload was truncated (e.g., >20 commits)
    created_at TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE public.events IS 'Stores raw event payloads from GitHub/Slack webhooks for auditability and processing.';
-- Create indexes for performance
CREATE INDEX idx_events_source ON public.events (source);
CREATE INDEX idx_events_delivery_id ON public.events (delivery_id);
COMMENT ON INDEX idx_events_source IS 'Index on source column for efficient filtering by slack/github.';
COMMENT ON INDEX idx_events_delivery_id IS 'Index on delivery_id for fast idempotency checks.';

-- Raw Data table: Stores summarized event content, linked to raw payloads
CREATE TABLE public.raw_data (
    id UUID PRIMARY KEY,
    source TEXT CHECK (source IN ('slack', 'github')) NOT NULL,
    content TEXT NOT NULL, -- Summarized content (e.g., "Push to nahom/kms by nahom")
    record_id TEXT NOT NULL, -- Unique ID (X-GitHub-Delivery or Slack-generated)
    event_id UUID REFERENCES public.events(id), -- Link to raw payload
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_raw_data_record_id ON public.raw_data (record_id);
COMMENT ON TABLE public.raw_data IS 'Stores summarized event content from Slack/GitHub, linked to raw payloads in events.';
COMMENT ON INDEX idx_raw_data_record_id IS 'Index on record_id for fast lookup of summarized content.';

-- Entities: Knowledge graph entities (PERSON, PROJECT, TICKET)
CREATE TABLE public.entities (
    id UUID PRIMARY KEY,
    type TEXT CHECK (type IN ('person', 'project', 'ticket')) NOT NULL,
    name TEXT NOT NULL, -- e.g., Nahom (person), nahom/kms (project), PR #435 (ticket)
    metadata JSONB, -- Additional data (e.g., email for person, url for project)
    active BOOLEAN DEFAULT TRUE, -- False if repo deleted or ticket closed
    search_vector TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', name || ' ' || coalesce(metadata->>'description', ''))
    ) STORED,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX entities_search_idx ON public.entities USING GIN(search_vector);
COMMENT ON TABLE public.entities IS 'Stores knowledge graph entities (PERSON, PROJECT, TICKET) extracted from events.';
COMMENT ON INDEX entities_search_idx IS 'GIN index on search_vector for full-text search of entities.';

-- Edges: Knowledge graph relationships (authored, assigned, fixes)
CREATE TABLE public.edges (
    id UUID PRIMARY KEY,
    source_id UUID REFERENCES public.entities(id) NOT NULL,
    target_id UUID REFERENCES public.entities(id) NOT NULL,
    type TEXT NOT NULL, -- e.g., authored, assigned, fixes
    metadata JSONB, -- Additional data (e.g., commit SHA, PR action)
    created_at TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE public.edges IS 'Stores relationships between entities (e.g., PERSON authored PROJECT).';

-- Contributions: Metrics for PERSON in PROJECT (commits, PRs, issues, bus factor)
CREATE TABLE public.contributions (
    id UUID PRIMARY KEY,
    person_name TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    commit_count INTEGER DEFAULT 0,
    pr_count INTEGER DEFAULT 0,
    issue_count INTEGER DEFAULT 0,
    bus_factor FLOAT DEFAULT 0.0 CHECK (bus_factor >= 0 AND bus_factor <= 1), -- 0-1 (1 = single contributor)
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(person_name, repo_name)
);
CREATE INDEX idx_contributions_repo_name ON public.contributions (repo_name);
COMMENT ON TABLE public.contributions IS 'Tracks contribution metrics per person per repository, including bus factor.';
COMMENT ON INDEX idx_contributions_repo_name IS 'Index on repo_name for efficient metrics queries by repository.';

-- Pull Requests: Detailed tracking of GitHub PRs
CREATE TABLE public.pull_requests (
    id UUID PRIMARY KEY,
    event_id UUID REFERENCES public.events(id),
    pr_number INTEGER NOT NULL,
    repo_name TEXT NOT NULL,
    title TEXT,
    body TEXT,
    assignee_id UUID REFERENCES public.entities(id),
    reviewers JSONB, -- Array of reviewer logins
    labels JSONB, -- Array of label names
    commits_count INTEGER,
    merged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(pr_number, repo_name)
);
CREATE INDEX idx_pull_requests_repo_name ON public.pull_requests (repo_name);
COMMENT ON TABLE public.pull_requests IS 'Stores detailed GitHub pull request data, linked to events.';
COMMENT ON INDEX idx_pull_requests_repo_name IS 'Index on repo_name for efficient PR queries by repository.';

-- Issues: Detailed tracking of GitHub issues
CREATE TABLE public.issues (
    id UUID PRIMARY KEY,
    event_id UUID REFERENCES public.events(id),
    issue_number INTEGER NOT NULL,
    repo_name TEXT NOT NULL,
    title TEXT,
    body TEXT,
    assignee_id UUID REFERENCES public.entities(id),
    labels JSONB, -- Array of label names
    state TEXT CHECK (state IN ('open', 'closed')) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(issue_number, repo_name)
);
CREATE INDEX idx_issues_repo_name ON public.issues (repo_name);
COMMENT ON TABLE public.issues IS 'Stores detailed GitHub issue data, linked to events.';
COMMENT ON INDEX idx_issues_repo_name IS 'Index on repo_name for efficient issue queries by repository.';
