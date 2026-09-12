from enum import Enum


class ScheduleType(str, Enum):
    """Periodic Task Schedule Type Enum."""

    CRONTAB = "crontab"
    INTERVAL = "interval"


class IntervalPeriod(str, Enum):
    """Interval Period Units Enum."""

    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


class CeleryRedisKeys(str, Enum):
    """Redis Keys for Celery Beat Scheduler Cache & Versioning."""

    SCHEDULE_DATA = "celery:beat_schedule_data"
    SCHEDULE_VERSION = "celery:schedule_version"


class DLQConstants:
    """Dead Letter Queue configuration constants."""

    DEFAULT_RETENTION_DAYS = 30
    EXCLUDED_TASKS = {
        "celery.ping",
        "celery.backend_cleanup",
        "celery.chain",
        "celery.group",
        "celery.chord",
        "dlq_tasks.clean_old_dlq_tasks",
    }
