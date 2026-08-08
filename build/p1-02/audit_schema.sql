-- P1-02: append-only, hash-chained audit log (Architecture v2.0 §8)
CREATE SEQUENCE audit_seq;
CREATE TABLE audit_log (
    seq          BIGINT PRIMARY KEY DEFAULT nextval('audit_seq'),
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor        TEXT NOT NULL,
    component    TEXT NOT NULL,
    action       TEXT NOT NULL,
    opp_id       TEXT,
    previous_value TEXT,
    new_value      TEXT,
    reason       TEXT,
    prev_hash    TEXT NOT NULL,
    entry_hash   TEXT NOT NULL
);
CREATE OR REPLACE FUNCTION reject_audit_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is forbidden', TG_OP;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE OR REPLACE FUNCTION chain_audit_row() RETURNS trigger AS $$
DECLARE
    last_hash TEXT;
BEGIN
    SELECT entry_hash INTO last_hash FROM audit_log ORDER BY seq DESC LIMIT 1;
    NEW.prev_hash := COALESCE(last_hash, 'GENESIS');
    NEW.entry_hash := encode(digest(NEW.prev_hash || '|' || NEW.ts::text || '|' ||
        NEW.actor || '|' || NEW.component || '|' || NEW.action || '|' ||
        COALESCE(NEW.opp_id,'') || '|' || COALESCE(NEW.new_value,''), 'sha256'), 'hex');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_chain BEFORE INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION chain_audit_row();
CREATE EXTENSION IF NOT EXISTS pgcrypto;
GRANT INSERT, SELECT ON audit_log TO orchestrator_app;
GRANT USAGE ON SEQUENCE audit_seq TO orchestrator_app;
