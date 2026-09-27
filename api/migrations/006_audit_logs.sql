-- up
-- Create audit_logs table
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID DEFAULT gen_random_uuid(),
    actor_id UUID NOT NULL,
    action VARCHAR NOT NULL,
    resource VARCHAR NOT NULL,
    resource_id VARCHAR NOT NULL,
    details JSONB NOT NULL,
    ip_address VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
);

-- Convert to TimescaleDB hypertable
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        BEGIN
            CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'create extension timescaledb error: %', SQLERRM;
        END;
    END IF;
    BEGIN
        PERFORM create_hypertable('audit_logs', 'created_at', if_not_exists => TRUE);
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'create_hypertable error: %', SQLERRM;
    END;
END $$;

-- Create indices
CREATE INDEX IF NOT EXISTS idx_audit_logs_details ON audit_logs USING GIN (details);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs (resource, resource_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs (actor_id, created_at DESC);

-- Create generic audit trigger function
CREATE OR REPLACE FUNCTION log_audit_trail()
RETURNS TRIGGER AS $$
DECLARE
    actor_id_val UUID;
    ip_addr_val  VARCHAR;
    res_id_val   VARCHAR;
    new_json     JSONB;
    old_json     JSONB;
    action_val   VARCHAR;
    resource_val VARCHAR;
BEGIN
    actor_id_val := NULLIF(current_setting('app.actor_id', true), '')::UUID;
    IF actor_id_val IS NULL THEN
        actor_id_val := '00000000-0000-0000-0000-000000000000'::UUID;
    END IF;

    ip_addr_val := NULLIF(current_setting('app.client_ip', true), '');

    IF TG_OP = 'DELETE' THEN
        old_json := to_jsonb(OLD);
        new_json := NULL;
        IF TG_TABLE_NAME = 'app_versions' THEN
            res_id_val := OLD.platform::TEXT;
        ELSE
            res_id_val := OLD.id::TEXT;
        END IF;
    ELSIF TG_OP = 'UPDATE' THEN
        old_json := to_jsonb(OLD);
        new_json := to_jsonb(NEW);
        IF TG_TABLE_NAME = 'app_versions' THEN
            res_id_val := NEW.platform::TEXT;
        ELSE
            res_id_val := NEW.id::TEXT;
        END IF;
    ELSE
        old_json := NULL;
        new_json := to_jsonb(NEW);
        IF TG_TABLE_NAME = 'app_versions' THEN
            res_id_val := NEW.platform::TEXT;
        ELSE
            res_id_val := NEW.id::TEXT;
        END IF;
    END IF;

    new_json := new_json - ARRAY['password_hash', 'hashed_password'];
    old_json := old_json - ARRAY['password_hash', 'hashed_password'];

    CASE
        WHEN TG_TABLE_NAME = 'users' THEN
            action_val := 'USER_' || (CASE WHEN TG_OP = 'INSERT' THEN 'CREATE' ELSE TG_OP END);
            resource_val := 'user';
        WHEN TG_TABLE_NAME = 'roles' THEN
            action_val := 'ROLE_' || (CASE WHEN TG_OP = 'INSERT' THEN 'CREATE' ELSE TG_OP END);
            resource_val := 'role';
        WHEN TG_TABLE_NAME = 'app_versions' THEN
            action_val := 'APP_VERSION_' || (CASE WHEN TG_OP = 'INSERT' THEN 'CREATE' ELSE TG_OP END);
            resource_val := 'app_version';
        WHEN TG_TABLE_NAME = 'periodic_tasks' THEN
            action_val := 'PERIODIC_TASK_' || (CASE WHEN TG_OP = 'INSERT' THEN 'CREATE' ELSE TG_OP END);
            resource_val := 'periodic_task';
        WHEN TG_TABLE_NAME = 'dead_letter_tasks' THEN
            action_val := 'DLQ_TASK_' || (CASE WHEN TG_OP = 'INSERT' THEN 'CREATE' ELSE TG_OP END);
            resource_val := 'dlq_task';
        ELSE
            action_val := UPPER(TG_TABLE_NAME) || '_' || (CASE WHEN TG_OP = 'INSERT' THEN 'CREATE' ELSE TG_OP END);
            resource_val := TG_TABLE_NAME;
    END CASE;

    INSERT INTO audit_logs (
        actor_id,
        action,
        resource,
        resource_id,
        details,
        ip_address
    ) VALUES (
        actor_id_val,
        action_val,
        resource_val,
        COALESCE(res_id_val, 'unknown'),
        jsonb_build_object('old', old_json, 'new', new_json),
        ip_addr_val
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Attach triggers to audited tables
DROP TRIGGER IF EXISTS trg_audit_users ON users;
CREATE TRIGGER trg_audit_users
AFTER INSERT OR UPDATE OR DELETE ON users
FOR EACH ROW EXECUTE FUNCTION log_audit_trail();

DROP TRIGGER IF EXISTS trg_audit_roles ON roles;
CREATE TRIGGER trg_audit_roles
AFTER INSERT OR UPDATE OR DELETE ON roles
FOR EACH ROW EXECUTE FUNCTION log_audit_trail();

DROP TRIGGER IF EXISTS trg_audit_app_versions ON app_versions;
CREATE TRIGGER trg_audit_app_versions
AFTER INSERT OR UPDATE OR DELETE ON app_versions
FOR EACH ROW EXECUTE FUNCTION log_audit_trail();

DROP TRIGGER IF EXISTS trg_audit_periodic_tasks ON periodic_tasks;
CREATE TRIGGER trg_audit_periodic_tasks
AFTER INSERT OR UPDATE OR DELETE ON periodic_tasks
FOR EACH ROW EXECUTE FUNCTION log_audit_trail();

DROP TRIGGER IF EXISTS trg_audit_dead_letter_tasks ON dead_letter_tasks;
CREATE TRIGGER trg_audit_dead_letter_tasks
AFTER INSERT OR UPDATE OR DELETE ON dead_letter_tasks
FOR EACH ROW EXECUTE FUNCTION log_audit_trail();

-- down
DROP TRIGGER IF EXISTS trg_audit_users ON users;
DROP TRIGGER IF EXISTS trg_audit_roles ON roles;
DROP TRIGGER IF EXISTS trg_audit_app_versions ON app_versions;
DROP TRIGGER IF EXISTS trg_audit_periodic_tasks ON periodic_tasks;
DROP TRIGGER IF EXISTS trg_audit_dead_letter_tasks ON dead_letter_tasks;
DROP FUNCTION IF EXISTS log_audit_trail();
DROP TABLE IF EXISTS audit_logs;
