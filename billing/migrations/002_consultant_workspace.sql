CREATE TABLE consulting_clients (
    client_id UUID PRIMARY KEY,
    owner_user_id UUID NOT NULL,
    name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 160),
    internal_reference TEXT CHECK (internal_reference IS NULL OR char_length(internal_reference) <= 120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_user_id, name),
    UNIQUE (owner_user_id, client_id)
);

CREATE TABLE analysis_snapshots (
    analysis_id UUID PRIMARY KEY,
    owner_user_id UUID NOT NULL,
    client_id UUID NOT NULL,
    dataset_hash TEXT NOT NULL CHECK (char_length(dataset_hash) = 64),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis_result JSONB NOT NULL,
    quality_status TEXT NOT NULL,
    insights JSONB NOT NULL DEFAULT '[]'::jsonb,
    executive_summary TEXT NOT NULL DEFAULT '',
    consultant_comment TEXT NOT NULL DEFAULT '',
    analysis_version TEXT NOT NULL DEFAULT '1',
    CHECK (period_start <= period_end),
    UNIQUE (owner_user_id, client_id, dataset_hash),
    UNIQUE (owner_user_id, client_id, analysis_id),
    FOREIGN KEY (owner_user_id, client_id)
        REFERENCES consulting_clients(owner_user_id, client_id) ON DELETE CASCADE
);

CREATE TABLE report_versions (
    report_id UUID PRIMARY KEY,
    owner_user_id UUID NOT NULL,
    client_id UUID NOT NULL,
    analysis_id UUID NOT NULL,
    report_version INTEGER NOT NULL CHECK (report_version > 0),
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    report_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_user_id, analysis_id, report_version),
    FOREIGN KEY (owner_user_id, client_id, analysis_id)
        REFERENCES analysis_snapshots(owner_user_id, client_id, analysis_id) ON DELETE CASCADE
);

CREATE INDEX consulting_clients_owner_idx ON consulting_clients (owner_user_id, updated_at DESC);
CREATE INDEX analysis_snapshots_owner_client_period_idx
    ON analysis_snapshots (owner_user_id, client_id, period_start DESC);
CREATE INDEX report_versions_owner_client_idx
    ON report_versions (owner_user_id, client_id, created_at DESC);
