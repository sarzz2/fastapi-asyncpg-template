-- up
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    name VARCHAR(100) NOT NULL,
    prefix VARCHAR(16) NOT NULL,
    hashed_key VARCHAR(64) UNIQUE NOT NULL,
    scopes TEXT[] NOT NULL DEFAULT '{}',
    rate_limit INTEGER,
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hashed_key ON api_keys(hashed_key);
CREATE INDEX IF NOT EXISTS idx_api_keys_is_active ON api_keys(is_active);
CREATE INDEX IF NOT EXISTS idx_api_keys_created_by ON api_keys(created_by);

CREATE TABLE IF NOT EXISTS webhook_endpoints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    url TEXT NOT NULL,
    secret VARCHAR(64) NOT NULL,
    description TEXT,
    event_types TEXT[] NOT NULL,
    headers JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_webhook_endpoints_is_active ON webhook_endpoints(is_active);
CREATE INDEX IF NOT EXISTS idx_webhook_endpoints_event_types ON webhook_endpoints USING GIN(event_types);
CREATE INDEX IF NOT EXISTS idx_webhook_endpoints_created_by ON webhook_endpoints(created_by);

CREATE TABLE IF NOT EXISTS webhook_logs (
    id UUID DEFAULT gen_random_uuid(),
    direction VARCHAR(10) NOT NULL,
    endpoint_id UUID REFERENCES webhook_endpoints(id) ON DELETE SET NULL,
    source VARCHAR(100) NOT NULL,
    event_name VARCHAR(100) NOT NULL,
    url TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    status_code INTEGER,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    request_headers JSONB,
    response_headers JSONB,
    response_body TEXT,
    execution_time_ms INTEGER,
    error_message TEXT,
    ip_address VARCHAR(45),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
);

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
        PERFORM create_hypertable('webhook_logs', 'created_at', if_not_exists => TRUE);
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'create_hypertable error: %', SQLERRM;
    END;
END $$;

CREATE INDEX IF NOT EXISTS idx_webhook_logs_direction ON webhook_logs (direction, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_logs_status ON webhook_logs (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_logs_event_name ON webhook_logs (event_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_logs_source ON webhook_logs (source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_logs_endpoint_id ON webhook_logs (endpoint_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_logs_payload ON webhook_logs USING GIN (payload);

INSERT INTO permissions (name, description) VALUES
('api_keys:create', 'Create API key'),
('api_keys:read', 'Read API keys'),
('api_keys:update', 'Update or rotate API key'),
('api_keys:delete', 'Delete API key'),
('webhooks:create', 'Create webhook endpoint'),
('webhooks:read', 'Read webhook endpoints and logs'),
('webhooks:update', 'Update webhook endpoint'),
('webhooks:delete', 'Delete webhook endpoint')
ON CONFLICT (name) DO NOTHING;

-- down
DELETE FROM permissions WHERE name IN (
    'api_keys:create', 'api_keys:read', 'api_keys:update', 'api_keys:delete',
    'webhooks:create', 'webhooks:read', 'webhooks:update', 'webhooks:delete'
);
DROP TABLE IF EXISTS webhook_logs;
DROP TABLE IF EXISTS webhook_endpoints;
DROP TABLE IF EXISTS api_keys;
