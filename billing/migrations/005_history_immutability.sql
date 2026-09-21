CREATE OR REPLACE FUNCTION prevent_history_update()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Historical records are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER analysis_snapshots_immutable
BEFORE UPDATE ON analysis_snapshots
FOR EACH ROW EXECUTE FUNCTION prevent_history_update();

CREATE TRIGGER report_versions_immutable
BEFORE UPDATE ON report_versions
FOR EACH ROW EXECUTE FUNCTION prevent_history_update();
