-- up
CREATE TABLE IF NOT EXISTS dead_letter_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id VARCHAR(255) NOT NULL,
    task_name VARCHAR(255) NOT NULL,
    queue VARCHAR(255) DEFAULT 'default',
    args JSONB DEFAULT '[]'::jsonb,
    kwargs JSONB DEFAULT '{}'::jsonb,
    headers JSONB DEFAULT '{}'::jsonb,
    exception_type VARCHAR(255),
    exception_message TEXT,
    traceback TEXT,
    retry_count INTEGER DEFAULT 0,
    failed_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dlq_task_name ON dead_letter_tasks (task_name);
CREATE INDEX IF NOT EXISTS idx_dlq_failed_at ON dead_letter_tasks (failed_at);
CREATE INDEX IF NOT EXISTS idx_dlq_task_id ON dead_letter_tasks (task_id);

INSERT INTO permissions (name, description) VALUES
('dlq:read', 'Read Celery dead letter queue tasks and statistics'),
('dlq:update', 'Edit payload args and kwargs of dead letter queue tasks'),
('dlq:retrigger', 'Retrigger failed tasks from dead letter queue'),
('dlq:delete', 'Discard or delete dead letter queue tasks')
ON CONFLICT (name) DO NOTHING;

-- down
DELETE FROM permissions WHERE name IN (
    'dlq:read',
    'dlq:update',
    'dlq:retrigger',
    'dlq:delete'
);
DROP TABLE IF EXISTS dead_letter_tasks;
