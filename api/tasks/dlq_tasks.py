"""
Celery Background Tasks for Dead Letter Queue Management.
"""

import logging

from celery import Task

from api.apps.common.constants import DLQConstants
from api.apps.common.v0.dao.dead_letter_task import DeadLetterTaskDAO
from api.core.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="dlq_tasks.clean_old_dlq_tasks")
def clean_old_dlq_tasks(self: Task, days: int = DLQConstants.DEFAULT_RETENTION_DAYS) -> None:
    """
    Celery task to purge Dead Letter Queue entries older than 30 days.

    Args:
        days (int): Retention days threshold (default: 30 days).
    """
    logger.info("Starting clean_old_dlq_tasks: purging entries older than %d days.", days)

    dao = DeadLetterTaskDAO(db=self.db)

    async def _purge() -> int:
        return await dao.delete_old_tasks(days=days)

    deleted_count = self.loop.run_until_complete(_purge())
    logger.info("Finished clean_old_dlq_tasks: purged %d old DLQ entries.", deleted_count)
