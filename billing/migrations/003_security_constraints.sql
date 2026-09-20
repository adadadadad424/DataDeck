ALTER TABLE billing_users
    ADD CONSTRAINT billing_users_email_length CHECK (char_length(email) BETWEEN 3 AND 320),
    ADD CONSTRAINT billing_users_oidc_issuer_length CHECK (char_length(oidc_issuer) BETWEEN 8 AND 500),
    ADD CONSTRAINT billing_users_oidc_subject_length CHECK (char_length(oidc_subject) BETWEEN 1 AND 500);

ALTER TABLE stripe_events
    ADD CONSTRAINT stripe_events_id_length CHECK (char_length(event_id) BETWEEN 1 AND 255),
    ADD CONSTRAINT stripe_events_type_length CHECK (char_length(event_type) BETWEEN 1 AND 160),
    ADD CONSTRAINT stripe_events_created_positive CHECK (event_created > 0);

ALTER TABLE analysis_snapshots
    ADD CONSTRAINT analysis_summary_length CHECK (char_length(executive_summary) <= 2000),
    ADD CONSTRAINT analysis_comment_length CHECK (char_length(consultant_comment) <= 2000),
    ADD CONSTRAINT analysis_quality_length CHECK (char_length(quality_status) BETWEEN 1 AND 40),
    ADD CONSTRAINT analysis_mapping_size CHECK (octet_length(mapping::text) <= 32000),
    ADD CONSTRAINT analysis_result_size CHECK (octet_length(analysis_result::text) <= 512000),
    ADD CONSTRAINT analysis_insights_size CHECK (octet_length(insights::text) <= 32000);

ALTER TABLE report_versions
    ADD CONSTRAINT report_settings_size CHECK (octet_length(settings::text) <= 16000),
    ADD CONSTRAINT report_hash_format CHECK (report_hash IS NULL OR report_hash ~ '^[0-9a-f]{64}$');

CREATE INDEX IF NOT EXISTS analysis_snapshots_owner_created_idx
    ON analysis_snapshots (owner_user_id, uploaded_at DESC);
CREATE INDEX IF NOT EXISTS stripe_events_processed_idx
    ON stripe_events (processed_at DESC);
