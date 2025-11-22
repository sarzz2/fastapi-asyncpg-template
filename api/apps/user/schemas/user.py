from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# Shared properties
class UserBase(BaseModel):
    """Base User schema with shared properties."""

    email: EmailStr
    username: str
    full_name: Optional[str] = None
    is_active: bool = True


class UserCreate(UserBase):
    """Schema for user creation request."""

    password: Optional[str] = None


class UserUpdate(BaseModel):
    """Schema for user update request."""

    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    username: Optional[str] = None


class UserData(UserBase):
    """Schema for user data in responses."""

    id: UUID
    is_superuser: bool
    hashed_password: str = Field(exclude=True)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserSessionBase(BaseModel):
    """Schema for user session data."""

    jti: str
    user_id: UUID
    issued_at: datetime
    expires_at: datetime
    ip_address: Optional[Union[str, IPv4Address, IPv6Address]] = None
    user_agent: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserSessionCreate(UserSessionBase):
    """Schema for creating a user session."""


class UserSessionData(UserSessionBase):
    """Schema representing user session as stored in database."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
