CREATE TABLE workspaces (
    workspace_id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 160),
    created_by UUID NOT NULL REFERENCES workspace_users(user_id) ON DELETE RESTRICT,
    base_plan TEXT NOT NULL DEFAULT 'beta' CHECK (base_plan IN ('free', 'beta', 'pro', 'enterprise')),
    included_seats INTEGER NOT NULL DEFAULT 1 CHECK (included_seats > 0),
    included_clients INTEGER NOT NULL DEFAULT 10 CHECK (included_clients > 0),
    extra_seats INTEGER NOT NULL DEFAULT 0 CHECK (extra_seats >= 0),
    extra_clients INTEGER NOT NULL DEFAULT 0 CHECK (extra_clients >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE workspace_members (
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES workspace_users(user_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('OWNER', 'PARTNER', 'CONSULTANT', 'VIEWER')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workspace_id, user_id)
);

INSERT INTO workspaces (workspace_id, name, created_by)
SELECT md5('datadeck-personal-workspace:' || user_id::text)::uuid, 'Persönlicher Workspace', user_id
FROM workspace_users
ON CONFLICT (workspace_id) DO NOTHING;

INSERT INTO workspace_members (workspace_id, user_id, role)
SELECT md5('datadeck-personal-workspace:' || user_id::text)::uuid, user_id, 'OWNER'
FROM workspace_users
ON CONFLICT (workspace_id, user_id) DO NOTHING;

ALTER TABLE consulting_clients ADD COLUMN workspace_id UUID;
UPDATE consulting_clients
SET workspace_id = md5('datadeck-personal-workspace:' || owner_user_id::text)::uuid;
ALTER TABLE consulting_clients
    ALTER COLUMN workspace_id SET NOT NULL,
    ADD CONSTRAINT consulting_clients_workspace_fk
        FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE;
CREATE UNIQUE INDEX consulting_clients_workspace_name_key
    ON consulting_clients (workspace_id, name);
CREATE UNIQUE INDEX consulting_clients_workspace_resource_key
    ON consulting_clients (workspace_id, client_id);

ALTER TABLE analysis_snapshots ADD COLUMN workspace_id UUID;
UPDATE analysis_snapshots
SET workspace_id = md5('datadeck-personal-workspace:' || owner_user_id::text)::uuid;
ALTER TABLE analysis_snapshots
    ALTER COLUMN workspace_id SET NOT NULL,
    DROP CONSTRAINT analysis_snapshots_owner_user_id_client_id_fkey,
    ADD CONSTRAINT analysis_snapshots_workspace_fk
        FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    ADD CONSTRAINT analysis_snapshots_actor_fk
        FOREIGN KEY (owner_user_id) REFERENCES workspace_users(user_id) ON DELETE RESTRICT,
    ADD CONSTRAINT analysis_snapshots_workspace_client_fk
        FOREIGN KEY (workspace_id, client_id)
        REFERENCES consulting_clients(workspace_id, client_id) ON DELETE CASCADE;
CREATE UNIQUE INDEX analysis_snapshots_workspace_resource_key
    ON analysis_snapshots (workspace_id, client_id, analysis_id);
CREATE UNIQUE INDEX analysis_snapshots_workspace_dataset_key
    ON analysis_snapshots (workspace_id, client_id, dataset_hash);
CREATE INDEX analysis_snapshots_workspace_client_period_idx
    ON analysis_snapshots (workspace_id, client_id, period_start DESC);

ALTER TABLE report_versions ADD COLUMN workspace_id UUID;
UPDATE report_versions
SET workspace_id = md5('datadeck-personal-workspace:' || owner_user_id::text)::uuid;
ALTER TABLE report_versions
    ALTER COLUMN workspace_id SET NOT NULL,
    DROP CONSTRAINT report_versions_owner_user_id_client_id_analysis_id_fkey,
    ADD CONSTRAINT report_versions_workspace_fk
        FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    ADD CONSTRAINT report_versions_actor_fk
        FOREIGN KEY (owner_user_id) REFERENCES workspace_users(user_id) ON DELETE RESTRICT,
    ADD CONSTRAINT report_versions_workspace_analysis_fk
        FOREIGN KEY (workspace_id, client_id, analysis_id)
        REFERENCES analysis_snapshots(workspace_id, client_id, analysis_id) ON DELETE CASCADE;
CREATE UNIQUE INDEX report_versions_workspace_version_key
    ON report_versions (workspace_id, analysis_id, report_version);
CREATE UNIQUE INDEX report_versions_workspace_resource_key
    ON report_versions (workspace_id, report_id);
CREATE INDEX report_versions_workspace_client_idx
    ON report_versions (workspace_id, client_id, created_at DESC);

CREATE TABLE audit_events (
    event_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    anonymous_actor_id TEXT NOT NULL CHECK (anonymous_actor_id ~ '^[0-9a-f]{32}$'),
    event_type TEXT NOT NULL CHECK (char_length(event_type) BETWEEN 1 AND 80),
    resource_type TEXT NOT NULL CHECK (char_length(resource_type) BETWEEN 1 AND 80),
    resource_id UUID,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (octet_length(metadata::text) <= 8000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX audit_events_workspace_created_idx
    ON audit_events (workspace_id, created_at DESC);

CREATE TRIGGER audit_events_immutable
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION prevent_history_update();

CREATE TABLE report_approvals (
    approval_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    report_id UUID NOT NULL,
    anonymous_approver_id TEXT NOT NULL CHECK (anonymous_approver_id ~ '^[0-9a-f]{32}$'),
    approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, report_id),
    FOREIGN KEY (workspace_id, report_id)
        REFERENCES report_versions(workspace_id, report_id) ON DELETE CASCADE
);

CREATE TABLE monitoring_findings (
    finding_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    client_id UUID NOT NULL,
    rule_id TEXT NOT NULL CHECK (char_length(rule_id) BETWEEN 1 AND 80),
    fingerprint TEXT NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'NOTICE', 'IMPORTANT')),
    status TEXT NOT NULL CHECK (status IN ('NEW', 'ONGOING', 'RESOLVED')),
    title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    detail TEXT NOT NULL CHECK (char_length(detail) BETWEEN 1 AND 1000),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (octet_length(evidence::text) <= 8000),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, client_id, rule_id, fingerprint),
    FOREIGN KEY (workspace_id, client_id)
        REFERENCES consulting_clients(workspace_id, client_id) ON DELETE CASCADE
);
CREATE INDEX monitoring_findings_workspace_status_idx
    ON monitoring_findings (workspace_id, client_id, status, last_seen_at DESC);
