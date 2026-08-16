-- up
CREATE TABLE IF NOT EXISTS periodic_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    task VARCHAR(255) NOT NULL,
    schedule_type VARCHAR(50) NOT NULL DEFAULT 'crontab',
    cron_minute VARCHAR(50) DEFAULT '*',
    cron_hour VARCHAR(50) DEFAULT '*',
    cron_day_of_week VARCHAR(50) DEFAULT '*',
    cron_day_of_month VARCHAR(50) DEFAULT '*',
    cron_month_of_year VARCHAR(50) DEFAULT '*',
    interval_every INTEGER DEFAULT NULL,
    interval_period VARCHAR(50) DEFAULT NULL,
    args JSONB DEFAULT '[]'::jsonb,
    kwargs JSONB DEFAULT '{}'::jsonb,
    enabled BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMPTZ DEFAULT NULL,
    total_run_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO permissions (name, description) VALUES
('periodic_tasks:create', 'Create a new periodic task schedule'),
('periodic_tasks:read', 'Read periodic task schedule details'),
('periodic_tasks:update', 'Update periodic task schedule'),
('periodic_tasks:delete', 'Delete a periodic task schedule'),
('periodic_tasks:trigger', 'Manually trigger a task on demand')
ON CONFLICT (name) DO NOTHING;

INSERT INTO periodic_tasks (name, task, schedule_type, cron_minute, cron_hour, cron_day_of_week, cron_day_of_month, cron_month_of_year)
VALUES ('delete-old-logs', 'api.tasks.delete_old_logs.delete_old_logs', 'crontab', '0', '0', '*', '*', '*')
ON CONFLICT (name) DO NOTHING;

-- down
DELETE FROM permissions WHERE name IN (
    'periodic_tasks:create',
    'periodic_tasks:read',
    'periodic_tasks:update',
    'periodic_tasks:delete',
    'periodic_tasks:trigger'
);
DROP TABLE IF EXISTS periodic_tasks;
