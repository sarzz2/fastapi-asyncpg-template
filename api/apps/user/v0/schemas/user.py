from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
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
