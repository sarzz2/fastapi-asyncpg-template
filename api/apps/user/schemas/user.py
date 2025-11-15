from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# Shared properties
class UserBase(BaseModel):
    """Base User schema with shared properties."""

    email: EmailStr
    username: str
    full_name: Optional[str] = None
    is_active: bool = True


class UserCreate(UserBase):
    """Schema for user creation request."""

    password: str


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


class UserLogin(BaseModel):
    """Schema for login request."""

    username: str
    password: str


class Token(BaseModel):
    """Schema for authentication token response."""

    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    """Schema for login response containing token and user data."""

    token: Token
    user: UserData


class TokenData(BaseModel):
    """Schema for decoded token data."""

    username: str
    id: Optional[UUID] = None
    exp: int
    jti: str
    type: str = "Bearer"


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


class RefreshTokenRequest(BaseModel):
    """Schema for refresh token request."""

    refresh_token: str
