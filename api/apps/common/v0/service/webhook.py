import logging
import secrets
from uuid import UUID

from fastapi import Depends, HTTPException, status

from api.apps.common.utils import validate_webhook_url
from api.apps.common.v0.dao.webhook import WebhookDAO, get_webhook_dao
from api.apps.common.v0.schemas.webhook import (
    WebhookEndpointCreate,
    WebhookEndpointCreateInternal,
    WebhookEndpointData,
    WebhookEndpointUpdate,
)
from api.core.celery_app import celery_app

logger = logging.getLogger("fastapi")


class WebhookService:
    """Service layer managing outbound webhook endpoint configurations and event dispatching."""

    def __init__(self, dao: WebhookDAO) -> None:
        """
        Initialize the WebhookService.
        Args:
            dao (WebhookDAO): The DAO for accessing webhook endpoint data.
        """
        self.dao = dao

    async def create_endpoint(
        self, endpoint_in: WebhookEndpointCreate, created_by: UUID | None = None
    ) -> WebhookEndpointData:
        """
        Register a new outbound webhook endpoint.
        Args:
            endpoint_in (WebhookEndpointCreate): The data for the webhook endpoint.
            created_by (UUID | None): The ID of the user who created the webhook endpoint.
        Returns:
            WebhookEndpointData: The created webhook endpoint configuration.
        """
        validate_webhook_url(endpoint_in.url)

        secret = endpoint_in.secret or f"whsec_{secrets.token_urlsafe(24)}"
        internal_data = WebhookEndpointCreateInternal(
            url=endpoint_in.url,
            description=endpoint_in.description,
            event_types=endpoint_in.event_types,
            headers=endpoint_in.headers,
            secret=secret,
            created_by=created_by,
        )

        return await self.dao.create_endpoint(internal_data)

    async def get_endpoint(self, endpoint_id: UUID) -> WebhookEndpointData:
        """
        Fetch webhook endpoint details by ID.
        Args:
            endpoint_id (UUID): The ID of the webhook endpoint.
        Returns:
            WebhookEndpointData: The webhook endpoint configuration.
        Raises:
            HTTPException:
                404 Not Found if the webhook endpoint is not found.
        """
        endpoint = await self.dao.get_endpoint_by_id(endpoint_id)
        if not endpoint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Webhook endpoint '{endpoint_id}' not found.",
            )
        return endpoint

    async def list_endpoints(
        self, limit: int = 50, cursor: str | None = None, is_active: bool | None = None
    ) -> list[WebhookEndpointData]:
        """
        List webhook endpoints.
        Args:
            limit (int): Maximum number of endpoints to return.
            cursor (str | None): Cursor for pagination (UUID of the last item).
            is_active (bool | None): Filter by active status.
        Returns:
            list[WebhookEndpointData]: List of webhook endpoint configurations.
        """
        return await self.dao.list_endpoints(limit=limit, cursor=cursor, is_active=is_active)

    async def update_endpoint(self, endpoint_id: UUID, update_in: WebhookEndpointUpdate) -> WebhookEndpointData:
        """
        Update a webhook endpoint.
        Args:
            endpoint_id (UUID): The ID of the webhook endpoint to update.
            update_in (WebhookEndpointUpdate): The data to update.
        Returns:
            WebhookEndpointData: The updated webhook endpoint configuration.
        Raises:
            HTTPException:
                404 Not Found if the webhook endpoint is not found.
        """
        if update_in.url:
            validate_webhook_url(update_in.url)

        await self.get_endpoint(endpoint_id)
        updated = await self.dao.update_endpoint(endpoint_id, update_in)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Webhook endpoint '{endpoint_id}' not found.",
            )
        return updated

    async def delete_endpoint(self, endpoint_id: UUID) -> None:
        """
        Delete a webhook endpoint.
        Args:
            endpoint_id (UUID): The ID of the webhook endpoint to delete.
        Raises:
            HTTPException:
                404 Not Found if the webhook endpoint is not found.
        """
        await self.get_endpoint(endpoint_id)
        deleted = await self.dao.delete_endpoint(endpoint_id)

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Failed to delete webhook endpoint '{endpoint_id}'.",
            )

    @classmethod
    async def dispatch_event_to_endpoints(cls, event_name: str, payload: dict, event_id: str) -> bool:
        """
        Enqueues Celery delivery task for all endpoints subscribed to event_name.
        Returns True if task was dispatched, False otherwise.
        Args:
            event_name (str): The name of the event to dispatch.
            payload (dict): The payload to send with the event.
            event_id (str): The ID of the event.
        Returns:
            bool: True if the task was dispatched, False otherwise.
        """
        celery_app.send_task(
            "common.send_webhook_event",
            args=[event_name, payload, event_id],
        )
        logger.info(
            "Dispatched webhook task for event '%s' (event_id=%s)",
            event_name,
            event_id,
        )
        return True


async def get_webhook_service(dao: WebhookDAO = Depends(get_webhook_dao)) -> WebhookService:
    """FastAPI dependency for WebhookService."""
    return WebhookService(dao=dao)
