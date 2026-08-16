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
