CREATE TABLE workspace_users (
    user_id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO workspace_users (user_id)
SELECT DISTINCT owner_user_id FROM consulting_clients
ON CONFLICT (user_id) DO NOTHING;

ALTER TABLE consulting_clients
    ADD CONSTRAINT consulting_clients_owner_fk
    FOREIGN KEY (owner_user_id) REFERENCES workspace_users(user_id) ON DELETE CASCADE;

ALTER TABLE analysis_snapshots
    ADD COLUMN analysis_engine_version TEXT NOT NULL DEFAULT 'legacy',
    ADD COLUMN analysis_schema_version INTEGER NOT NULL DEFAULT 1,
    ADD CONSTRAINT analysis_engine_version_length
        CHECK (char_length(analysis_engine_version) BETWEEN 1 AND 80),
    ADD CONSTRAINT analysis_schema_version_positive
        CHECK (analysis_schema_version > 0);

CREATE INDEX analysis_snapshots_owner_client_period_end_idx
    ON analysis_snapshots (owner_user_id, client_id, period_end DESC);
CREATE INDEX analysis_snapshots_dataset_hash_idx
    ON analysis_snapshots (dataset_hash);
CREATE INDEX report_versions_analysis_created_idx
    ON report_versions (analysis_id, created_at DESC);
