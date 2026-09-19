"""
Celery Background Tasks for Dead Letter Queue Management.
"""

import logging

from api.apps.common.constants import DLQConstants
from api.core.celery_app import AsyncBaseTask, celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="dlq_tasks.clean_old_dlq_tasks")
def clean_old_dlq_tasks(self: AsyncBaseTask, days: int = DLQConstants.DEFAULT_RETENTION_DAYS) -> None:
    """
    Celery task to purge Dead Letter Queue entries older than 30 days.

    Args:
        days (int): Retention days threshold (default: 30 days).
    """
    logger.info("Starting clean_old_dlq_tasks: purging entries older than %d days.", days)

    dao = self.container.dead_letter_task_dao

    async def _purge() -> int:
        return await dao.delete_old_tasks(days=days)

    deleted_count = self.loop.run_until_complete(_purge())
    logger.info("Finished clean_old_dlq_tasks: purged %d old DLQ entries.", deleted_count)
