-- Migration: 003_app_versions
-- Description: Create app_versions table to manage force updates

-- up
CREATE TABLE IF NOT EXISTS app_versions (
    platform VARCHAR(50) PRIMARY KEY, -- 'ios', 'android', 'web'
    min_build INTEGER NOT NULL DEFAULT 0,
    latest_build INTEGER NOT NULL DEFAULT 0,
    force_update BOOLEAN NOT NULL DEFAULT false,
    update_message TEXT,
    update_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Insert initial values
INSERT INTO app_versions (platform, min_build, latest_build, force_update, update_message)
VALUES
    ('ios', 1, 1, false, 'A new version is available. Please update.'),
    ('android', 1, 1, false, 'A new version is available. Please update.')
ON CONFLICT (platform) DO NOTHING;

-- Insert permissions for app version management
INSERT INTO permissions (name, description) VALUES
    ('app:read', 'View app version configurations'),
    ('app:update', 'Update app version configurations')
ON CONFLICT (name) DO NOTHING;

-- down
DROP TABLE IF EXISTS app_versions;
