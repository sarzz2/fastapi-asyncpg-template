import json
from datetime import datetime
from uuid import UUID

from fastapi import Depends

from api.apps.common.v0.schemas.webhook_log import WebhookLogCreate, WebhookLogData, WebhookLogFilterParams
from api.core.database import DataBase, get_db


class WebhookLogDAO:
    """Data Access Object for TimescaleDB webhook_logs hypertable."""

    def __init__(self, db: DataBase) -> None:
        self.db = db

    async def create_log(self, log_in: WebhookLogCreate) -> WebhookLogData:
        """
        Insert a new webhook log entry (inbound or outbound).

        Args:
            log_in (WebhookLogCreate): The webhook log entry to insert.

        Returns:
            WebhookLogData: The inserted webhook log entry.

        Raises:
            DataBaseError: If the log entry cannot be inserted.
        """
        query = """
            INSERT INTO webhook_logs (
                direction, endpoint_id, source, event_name, url, status,
                status_code, payload, request_headers, response_headers,
                response_body, execution_time_ms, error_message, ip_address
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8::jsonb, $9::jsonb, $10::jsonb,
                $11, $12, $13, $14
            )
            RETURNING *
        """
        payload_json = json.dumps(log_in.payload) if log_in.payload is not None else "{}"
        req_headers_json = json.dumps(log_in.request_headers) if log_in.request_headers is not None else None
        res_headers_json = json.dumps(log_in.response_headers) if log_in.response_headers is not None else None

        # Truncate response_body if necessary (max 2048 chars)
        res_body = log_in.response_body[:2048] if log_in.response_body else None

        return await self.db.write(
            query,
            log_in.direction.value,
            log_in.endpoint_id,
            log_in.source,
            log_in.event_name,
            log_in.url,
            log_in.status.value,
            log_in.status_code,
            payload_json,
            req_headers_json,
            res_headers_json,
            res_body,
            log_in.execution_time_ms,
            log_in.error_message,
            log_in.ip_address,
            model=WebhookLogData,
        )

    async def get_log_by_id(self, log_id: UUID, created_at: datetime | None = None) -> WebhookLogData | None:
        """
        Fetch a specific log entry by ID and optional created_at for hypertable partition pruning.

        Args:
            log_id (UUID): The ID of the log entry to fetch.
            created_at (datetime | None): The created_at timestamp for partition pruning.

        Returns:
            WebhookLogData | None: The fetched log entry.

        Raises:
            DataBaseError: If the log entry cannot be fetched.
        """
        if created_at:
            query = "SELECT * FROM webhook_logs WHERE id = $1 AND created_at = $2"
            return await self.db.fetch(query, log_id, created_at, model=WebhookLogData, fetch_row=True)
        query = "SELECT * FROM webhook_logs WHERE id = $1 ORDER BY created_at DESC LIMIT 1"
        return await self.db.fetch(query, log_id, model=WebhookLogData, fetch_row=True)

    async def list_logs(
        self,
        limit: int,
        cursor: str | None = None,
        filter_params: WebhookLogFilterParams | None = None,
    ) -> list[WebhookLogData]:
        """
        List webhook logs with filtering across direction, status, event, and date ranges.

        Args:
            limit (int): The maximum number of log entries to return.
            cursor (str | None): The cursor for pagination.
            filter_params (WebhookLogFilterParams | None): The filter parameters.

        Returns:
            list[WebhookLogData]: The list of log entries.

        Raises:
            DataBaseError: If the log entries cannot be fetched.
        """
        conditions = ["1=1"]
        params: list[object] = []

        if filter_params:
            if filter_params.direction:
                params.append(filter_params.direction.value)
                conditions.append(f"direction = ${len(params)}")

            if filter_params.status:
                params.append(filter_params.status.value)
                conditions.append(f"status = ${len(params)}")

            if filter_params.source:
                params.append(filter_params.source)
                conditions.append(f"source = ${len(params)}")

            if filter_params.event_name:
                params.append(filter_params.event_name)
                conditions.append(f"event_name = ${len(params)}")

            if filter_params.endpoint_id:
                params.append(filter_params.endpoint_id)
                conditions.append(f"endpoint_id = ${len(params)}::uuid")

            if filter_params.from_date:
                params.append(filter_params.from_date)
                conditions.append(f"created_at >= ${len(params)}")

            if filter_params.to_date:
                params.append(filter_params.to_date)
                conditions.append(f"created_at <= ${len(params)}")

        if cursor:
            params.append(cursor)
            conditions.append(f"created_at < ${len(params)}::timestamptz")

        params.append(limit)
        limit_idx = len(params)

        query_parts = [
            "SELECT * FROM webhook_logs WHERE",
            " AND ".join(conditions),
            "ORDER BY created_at DESC LIMIT",
            f"${limit_idx};",
        ]
        return await self.db.fetch(" ".join(query_parts), *params, model=WebhookLogData, fetch_row=False)


async def get_webhook_log_dao(db: DataBase = Depends(get_db)) -> WebhookLogDAO:
    """FastAPI dependency for WebhookLogDAO."""
    return WebhookLogDAO(db=db)
