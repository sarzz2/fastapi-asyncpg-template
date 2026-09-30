from datetime import datetime
from uuid import UUID

from fastapi import Depends, HTTPException, status

from api.apps.common.v0.dao.webhook_log import WebhookLogDAO, get_webhook_log_dao
from api.apps.common.v0.schemas.webhook_log import WebhookLogCreate, WebhookLogData, WebhookLogFilterParams


class WebhookLogService:
    """Service layer managing TimescaleDB webhook logs (inbound and outbound)."""

    def __init__(self, dao: WebhookLogDAO) -> None:
        self.dao = dao

    async def log_event(self, log_in: WebhookLogCreate) -> WebhookLogData:
        """Create a new webhook log entry.
        Args:
            log_in (WebhookLogCreate): The webhook log entry to insert.
        Returns:
            WebhookLogData: The inserted webhook log entry.
        Raises:
            DataBaseError: If the log entry cannot be inserted.
        """
        return await self.dao.create_log(log_in)

    async def get_log(self, log_id: UUID, created_at: datetime | None = None) -> WebhookLogData:
        """Retrieve a specific webhook log entry.
        Args:
            log_id (UUID): The ID of the log entry to fetch.
            created_at (datetime | None): The created_at timestamp for partition pruning.
        Returns:
            WebhookLogData | None: The fetched log entry.
        Raises:
            DataBaseError: If the log entry cannot be fetched.
        """
        log_entry = await self.dao.get_log_by_id(log_id, created_at=created_at)
        if not log_entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Webhook log entry '{log_id}' not found.",
            )
        return log_entry

    async def list_logs(
        self,
        limit: int = 50,
        cursor: str | None = None,
        filter_params: WebhookLogFilterParams | None = None,
    ) -> list[WebhookLogData]:
        """List webhook logs with filters.
        Args:
            limit (int): The maximum number of log entries to return.
            cursor (str | None): The cursor for pagination.
            filter_params (WebhookLogFilterParams | None): The filter parameters.
        Returns:
            list[WebhookLogData]: The list of log entries.
        Raises:
            DataBaseError: If the log entries cannot be fetched.
        """
        return await self.dao.list_logs(limit=limit, cursor=cursor, filter_params=filter_params)


async def get_webhook_log_service(
    dao: WebhookLogDAO = Depends(get_webhook_log_dao),
) -> WebhookLogService:
    """FastAPI dependency for WebhookLogService."""
    return WebhookLogService(dao=dao)
