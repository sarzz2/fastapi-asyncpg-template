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


class WebhookDirection(str, Enum):
    """Direction of webhook traffic."""

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class WebhookStatus(str, Enum):
    """Execution status for webhook logs."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class WebhookEvents(str, Enum):
    """Supported outbound webhook event types."""

    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"


# API Key Configuration Constants
API_KEY_CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days
API_KEY_LAST_USED_THROTTLE_SECONDS = 300  # 5 minutes


class NotificationChannels(str, Enum):
    """Notification delivery channel names."""

    SSE = "sse"
    EMAIL = "email"
    FCM = "fcm"
