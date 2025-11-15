from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


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
    oauth_provider: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def password_required_if_not_oauth(cls, v: dict) -> dict:
        """Ensure password is provided if not using OAuth."""
        if not v.get("password") and not v.get("oauth_provider"):
            raise ValueError("Password is required for non-OAuth users")
        return v


class UserUpdate(BaseModel):
    """Schema for user update request."""

    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    password: Optional[str] = None


class UserData(UserBase):
    """Schema for user data in responses."""

    id: UUID
    is_superuser: bool
    hashed_password: str = Field(exclude=True)
    created_at: datetime

    class Config:
        """Configure Pydantic model."""

        from_attributes = True


class UserSessionBase(BaseModel):
    """Schema for user session data."""

    jti: str
    user_id: UUID
    issued_at: datetime
    expires_at: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    class Config:
        """Configure Pydantic model."""

        from_attributes = True


class UserSessionCreate(UserSessionBase):
    """Schema for creating a user session."""


class UserSessionData(UserSessionBase):
    """Schema representing user session as stored in database."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        """Configure Pydantic model."""

        from_attributes = True
