-- up
-- 1. Insert impersonation permission
INSERT INTO permissions (name, description) VALUES
('users:impersonate', 'Impersonate another user for support, diagnostics, and testing')
ON CONFLICT (name) DO NOTHING;

-- 2. Add impersonator_id column to audit_logs table
ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS impersonator_id UUID;

CREATE INDEX IF NOT EXISTS idx_audit_logs_impersonator
ON audit_logs(impersonator_id, created_at DESC)
WHERE impersonator_id IS NOT NULL;

-- 3. Replace log_audit_trail() trigger function to capture app.impersonator_id
CREATE OR REPLACE FUNCTION log_audit_trail()
RETURNS TRIGGER AS $$
DECLARE
    actor_id_val        UUID;
    impersonator_id_val UUID;
    ip_addr_val         VARCHAR;
    res_id_val          VARCHAR;
    new_json            JSONB;
    old_json            JSONB;
    action_val          VARCHAR;
    resource_val        VARCHAR;
BEGIN
    actor_id_val := NULLIF(current_setting('app.actor_id', true), '')::UUID;
    IF actor_id_val IS NULL THEN
        actor_id_val := '00000000-0000-0000-0000-000000000000'::UUID;
    END IF;

    impersonator_id_val := NULLIF(current_setting('app.impersonator_id', true), '')::UUID;
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
        impersonator_id,
        action,
        resource,
        resource_id,
        details,
        ip_address
    ) VALUES (
        actor_id_val,
        impersonator_id_val,
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

-- down
DROP INDEX IF EXISTS idx_audit_logs_impersonator;
ALTER TABLE audit_logs DROP COLUMN IF EXISTS impersonator_id;
DELETE FROM permissions WHERE name = 'users:impersonate';
