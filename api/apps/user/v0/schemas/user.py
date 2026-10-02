import json
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from api.apps.user.v0.schemas.role import RoleData
from api.utils.pydantic_utils import StrongPassword, generate_file_url


# Shared properties
class UserBase(BaseModel):
    """Base User schema with shared properties."""

    email: EmailStr
    username: str
    full_name: str | None = None
    is_active: bool = True


class UserCreate(UserBase):
    """Schema for user creation request."""

    password: StrongPassword | None = None


class UserUpdate(BaseModel):
    """Schema for user update request."""

    full_name: str | None = None
    email: EmailStr | None = None
    username: str | None = None


class UserData(UserBase):
    """Schema for user data in responses."""

    id: UUID
    hashed_password: str | None = Field(None, exclude=True)
    created_at: datetime
    profile_picture_url: str | None = None
    roles: list[RoleData] = []
    token_version: int = 1

    model_config = ConfigDict(from_attributes=True)

    @field_validator("profile_picture_url", mode="before")
    @classmethod
    def generate_profile_picture_url(cls, v: str | None) -> str | None:
        """Generate profile picture URL."""
        return generate_file_url(v)


class UserSessionBase(BaseModel):
    """Schema for user session data."""

    jti: str
    user_id: UUID
    issued_at: datetime
    expires_at: datetime
    ip_address: str | IPv4Address | IPv6Address | None = None
    user_agent: str | None = None

    model_config = ConfigDict(from_attributes=True)


class UserSessionCreate(UserSessionBase):
    """Schema for creating a user session."""


class UserSessionData(UserSessionBase):
    """Schema representing user session as stored in database."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserRoleAssignment(BaseModel):
    """Schema for assigning roles to a user."""

    role_ids: list[UUID]


class UserTwoFactorData(BaseModel):
    """Schema for user two-factor authentication configuration."""

    id: UUID
    user_id: UUID
    is_enabled: bool = False
    secret_encrypted: str
    backup_codes: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    def model_post_init(self, context: Any, /) -> None:
        """Ensure backup_codes is parsed into list[dict[str, Any]] after model construction."""
        if isinstance(self.backup_codes, str):
            try:
                loaded = json.loads(self.backup_codes)
                if isinstance(loaded, str):
                    loaded = json.loads(loaded)
                self.backup_codes = [dict(c) for c in loaded] if isinstance(loaded, list) else []
            except (json.JSONDecodeError, TypeError, ValueError):
                self.backup_codes = []
        elif isinstance(self.backup_codes, list):
            self.backup_codes = [dict(c) for c in self.backup_codes if isinstance(c, dict)]
        else:
            self.backup_codes = []

    @field_validator("backup_codes", mode="before")
    @classmethod
    def parse_backup_codes(cls, v: Any) -> list[dict[str, Any]]:
        """Parse backup codes from JSON string if needed."""
        if isinstance(v, str):
            loaded: list[dict[str, Any]] = list(json.loads(v))
            return loaded
        if isinstance(v, list):
            item_list: list[dict[str, Any]] = list(v)
            return item_list
        return []
