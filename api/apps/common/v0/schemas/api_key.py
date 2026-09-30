from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    """Schema for creating a new API key."""

    name: str = Field(..., min_length=1, max_length=100, description="Friendly label or client name")
    scopes: list[str] = Field(default_factory=list, description="List of granular scopes or permissions")
    rate_limit: int | None = Field(default=None, ge=1, description="Rate limit (requests/min)")
    expires_at: datetime | None = Field(default=None, description="Optional key expiration timestamp")


class ApiKeyCreateInternal(ApiKeyCreate):
    """Internal schema for persisting an API key with generated cryptographic fields."""

    prefix: str = Field(..., max_length=16)
    hashed_key: str = Field(..., max_length=64)
    created_by: UUID | None = None
    is_active: bool = True


class ApiKeyUpdate(BaseModel):
    """Schema for updating an existing API key."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    scopes: list[str] | None = None
    rate_limit: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
    is_active: bool | None = None


class ApiKeyData(BaseModel):
    """Schema for API key metadata (masked, hashed key omitted)."""

    id: UUID
    created_by: UUID | None = None
    name: str
    prefix: str
    hashed_key: str | None = Field(default=None, exclude=True)
    scopes: list[str] = Field(default_factory=list)
    rate_limit: int | None = None
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreateResponse(ApiKeyData):
    """Schema returned once upon creation containing the raw secret key."""

    key: str = Field(..., description="Raw secret API key. Store this safely as it will not be shown again.")


class ApiKeyRotateResponse(ApiKeyData):
    """Schema returned upon key rotation containing the new raw secret key."""

    key: str = Field(..., description="Newly generated raw secret key. Store this safely.")
