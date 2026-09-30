import json
from uuid import UUID

from fastapi import Depends

from api.apps.common.v0.schemas.webhook import WebhookEndpointCreateInternal, WebhookEndpointData, WebhookEndpointUpdate
from api.core.database import DataBase, get_db


class WebhookDAO:
    """Data Access Object for Webhook Endpoint database operations."""

    def __init__(self, db: DataBase) -> None:
        self.db = db

    async def create_endpoint(
        self,
        endpoint_in: WebhookEndpointCreateInternal,
    ) -> WebhookEndpointData:
        """
        Create a new webhook endpoint configuration.

        Args:
            endpoint_in (WebhookEndpointCreateInternal): The webhook endpoint configuration schema.

        Returns:
            WebhookEndpointData: The created webhook endpoint configuration.
        """
        query = """
            INSERT INTO webhook_endpoints (url, secret, description, event_types, headers, created_by)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6)
            RETURNING *
        """
        headers_json = json.dumps(endpoint_in.headers)
        return await self.db.write(
            query,
            endpoint_in.url,
            endpoint_in.secret,
            endpoint_in.description,
            endpoint_in.event_types,
            headers_json,
            endpoint_in.created_by,
            model=WebhookEndpointData,
        )

    async def get_endpoint_by_id(self, endpoint_id: UUID) -> WebhookEndpointData | None:
        """
        Fetch webhook endpoint by UUID.
        Args:
            endpoint_id (UUID): The ID of the webhook endpoint.
        Returns:
            WebhookEndpointData | None: The webhook endpoint configuration if found, None otherwise.
        """
        query = "SELECT * FROM webhook_endpoints WHERE id = $1"
        return await self.db.fetch(query, endpoint_id, model=WebhookEndpointData, fetch_row=True)

    async def list_endpoints(
        self,
        limit: int,
        cursor: str | None = None,
        is_active: bool | None = None,
    ) -> list[WebhookEndpointData]:
        """
        List webhook endpoints with optional status filter and cursor pagination.
        Args:
            limit (int): Maximum number of endpoints to return.
            cursor (str | None): Cursor for pagination (UUID of the last item).
            is_active (bool | None): Filter by active status.
        Returns:
            list[WebhookEndpointData]: List of webhook endpoint configurations.
        """
        conditions = ["1=1"]
        params: list[object] = []

        if is_active is not None:
            params.append(is_active)
            conditions.append(f"is_active = ${len(params)}")

        if cursor:
            params.append(cursor)
            conditions.append(f"id < ${len(params)}::uuid")

        params.append(limit)
        limit_idx = len(params)

        query_parts = [
            "SELECT * FROM webhook_endpoints WHERE",
            " AND ".join(conditions),
            "ORDER BY id DESC LIMIT",
            f"${limit_idx};",
        ]
        return await self.db.fetch(" ".join(query_parts), *params, model=WebhookEndpointData, fetch_row=False)

    async def list_active_endpoints_for_event(self, event_name: str) -> list[WebhookEndpointData]:
        """
        List all active webhook endpoints subscribed to a specific event.
        Args:
            event_name (str): The name of the event to filter by.
        Returns:
            list[WebhookEndpointData]: List of active webhook endpoint configurations for the event.
        """
        query = """
            SELECT * FROM webhook_endpoints
            WHERE is_active = TRUE
              AND $1 = ANY(event_types)
            ORDER BY created_at ASC
        """
        return await self.db.fetch(query, event_name, model=WebhookEndpointData, fetch_row=False)

    async def update_endpoint(
        self, endpoint_id: UUID, update_data: WebhookEndpointUpdate
    ) -> WebhookEndpointData | None:
        """
        Update an existing webhook endpoint configuration.
        Args:
            endpoint_id (UUID): The ID of the webhook endpoint to update.
            update_data (WebhookEndpointUpdate): The data to update.
        Returns:
            WebhookEndpointData | None: The updated webhook endpoint configuration if found, None otherwise.
        """
        headers_val = json.dumps(update_data.headers) if update_data.headers is not None else None
        query = """
            UPDATE webhook_endpoints
            SET
                url = COALESCE($2, url),
                description = COALESCE($3, description),
                event_types = COALESCE($4, event_types),
                headers = COALESCE($5::jsonb, headers),
                secret = COALESCE($6, secret),
                is_active = COALESCE($7, is_active),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            RETURNING *
        """
        return await self.db.write(
            query,
            endpoint_id,
            update_data.url,
            update_data.description,
            update_data.event_types,
            headers_val,
            update_data.secret,
            update_data.is_active,
            model=WebhookEndpointData,
        )

    async def delete_endpoint(self, endpoint_id: UUID) -> bool:
        """
        Delete a webhook endpoint.
        Args:
            endpoint_id (UUID): The ID of the webhook endpoint to delete.
        Returns:
            bool: True if the webhook endpoint was deleted, False otherwise.
        """
        query = "DELETE FROM webhook_endpoints WHERE id = $1"
        res = await self.db.execute(query, endpoint_id)
        return " 0" not in res


async def get_webhook_dao(db: DataBase = Depends(get_db)) -> WebhookDAO:
    """FastAPI dependency for WebhookDAO."""
    return WebhookDAO(db=db)
