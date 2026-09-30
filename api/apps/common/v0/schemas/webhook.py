from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.apps.common.constants import WebhookEvents


class WebhookEndpointCreate(BaseModel):
    """Schema for registering a new outbound webhook endpoint."""

    url: str = Field(..., min_length=7, max_length=2048, description="Target destination HTTP/HTTPS URL")
    description: str | None = Field(default=None, max_length=255, description="Purpose or description")
    event_types: list[str] = Field(..., min_length=1, description="List of event names to subscribe to")
    headers: dict[str, str] = Field(default_factory=dict, description="Custom headers to include with delivery")
    secret: str | None = Field(
        default=None,
        min_length=16,
        max_length=64,
        description="Optional custom HMAC signing secret (auto-generated if omitted)",
    )

    @field_validator("secret", mode="before")
    @classmethod
    def empty_secret_to_none(cls, v: Any) -> Any:
        """Convert empty string secret to None."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, v: list[str]) -> list[str]:
        """Validate that all subscribed events belong to WebhookEvents."""
        valid_events = {e.value for e in WebhookEvents}
        for event in v:
            if event not in valid_events:
                raise ValueError(f"Invalid event '{event}'. Allowed events: {sorted(list(valid_events))}")
        return list(set(v))


class WebhookEndpointCreateInternal(WebhookEndpointCreate):
    """Internal schema for creating a webhook endpoint in DAO."""

    created_by: UUID | None = None


class WebhookEndpointUpdate(BaseModel):
    """Schema for updating an existing webhook endpoint."""

    url: str | None = Field(default=None, min_length=7, max_length=2048)
    description: str | None = Field(default=None, max_length=255)
    event_types: list[str] | None = None
    headers: dict[str, str] | None = None
    secret: str | None = Field(default=None, min_length=16, max_length=64)
    is_active: bool | None = None

    @field_validator("secret", mode="before")
    @classmethod
    def empty_secret_to_none(cls, v: Any) -> Any:
        """Convert empty string secret to None."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, v: list[str] | None) -> list[str] | None:
        """Validate that all subscribed events belong to WebhookEvents."""
        if v is None:
            return None
        if not v:
            raise ValueError("event_types cannot be empty if specified.")
        valid_events = {e.value for e in WebhookEvents}
        for event in v:
            if event not in valid_events:
                raise ValueError(f"Invalid event '{event}'. Allowed events: {sorted(list(valid_events))}")
        return list(set(v))


class WebhookEndpointData(BaseModel):
    """Schema for webhook endpoint details."""

    id: UUID
    created_by: UUID | None = None
    url: str
    secret: str
    description: str | None = None
    event_types: list[str] = Field(default_factory=list)
    headers: dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
