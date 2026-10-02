-- up
CREATE TABLE IF NOT EXISTS system_configurations (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enforce_mfa BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL
);

INSERT INTO system_configurations (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

INSERT INTO permissions (name, description) VALUES
('system_config:read', 'Read system configuration'),
('system_config:update', 'Update system configuration')
ON CONFLICT (name) DO NOTHING;

-- down
DELETE FROM permissions WHERE name IN ('system_config:read', 'system_config:update');
DROP TABLE IF EXISTS system_configurations;
