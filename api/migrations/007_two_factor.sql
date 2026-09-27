-- up
CREATE TABLE IF NOT EXISTS user_two_factor (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    secret_encrypted TEXT NOT NULL,
    backup_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_two_factor_user_id UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_two_factor_user_id ON user_two_factor(user_id);

-- down
DROP INDEX IF EXISTS idx_user_two_factor_user_id;
DROP TABLE IF EXISTS user_two_factor;
