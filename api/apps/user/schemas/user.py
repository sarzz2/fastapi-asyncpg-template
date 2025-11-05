from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


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


class UserUpdate(UserBase):
    """Schema for user update request."""

    password: Optional[str] = None


class UserInDB(UserBase):
    """Schema representing user as stored in database."""

    id: int
    hashed_password: str
    is_superuser: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        """Configure Pydantic model."""

        from_attributes = True


class UserResponse(UserBase):
    """Schema for user data in responses."""

    id: int
    is_superuser: bool
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
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Schema for decoded token data."""

    username: str
    id: int
    exp: int
    type: str = "Bearer"
