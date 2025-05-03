from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("servit")
celery_app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
    task_serializer="json",
    accept_content=["json"],
)

celery_app.conf.beat_schedule = {
    "delete_old_logs_daily": {
        "task": "app.tasks.delete_old_logs.delete_old_logs",
        "schedule": crontab(minute="0", hour="0"),
    },
}

celery_app.autodiscover_tasks(["app.tasks"])
