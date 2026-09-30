from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from api.apps.common.constants import WebhookDirection, WebhookStatus


class WebhookLogCreate(BaseModel):
    """Schema for creating a log entry in TimescaleDB webhook_logs."""

    direction: WebhookDirection = Field(..., description="INBOUND or OUTBOUND")
    endpoint_id: UUID | None = Field(default=None, description="Associated webhook endpoint ID if outbound")
    source: str = Field(..., max_length=100, description="Source or provider e.g. system, stripe, github")
    event_name: str = Field(..., max_length=100, description="Application or external event name")
    url: str = Field(..., description="Target destination URL or inbound request path")
    status: WebhookStatus = Field(..., description="SUCCESS, FAILED, or RETRYING")
    status_code: int | None = Field(default=None, description="HTTP response or return status code")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event body payload")
    request_headers: dict[str, Any] | None = Field(default=None, description="Headers sent or received")
    response_headers: dict[str, Any] | None = Field(default=None, description="Headers received in response")
    response_body: str | None = Field(default=None, description="Truncated body of the response")
    execution_time_ms: int | None = Field(default=None, ge=0, description="Roundtrip execution duration in ms")
    error_message: str | None = Field(default=None, description="Error message or exception string if failed")
    ip_address: str | None = Field(default=None, max_length=45, description="Client or server IP address")


class WebhookLogData(BaseModel):
    """Schema for viewing a webhook log entry."""

    id: UUID
    direction: str
    endpoint_id: UUID | None = None
    source: str
    event_name: str
    url: str
    status: str
    status_code: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    request_headers: dict[str, Any] | None = None
    response_headers: dict[str, Any] | None = None
    response_body: str | None = None
    execution_time_ms: int | None = None
    error_message: str | None = None
    ip_address: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WebhookLogFilterParams(BaseModel):
    """Schema for querying webhook logs with filters."""

    direction: WebhookDirection | None = None
    status: WebhookStatus | None = None
    event_name: str | None = None
    source: str | None = None
    endpoint_id: UUID | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
