from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from api.apps.user.schemas.user import UserData


class UserLogin(BaseModel):
    """Schema for login request."""

    username: str
    password: str


class Token(BaseModel):
    """Schema for authentication token response."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"


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


class RefreshTokenRequest(BaseModel):
    """Schema for refresh token request."""

    refresh_token: str


class SudoTokenRequest(BaseModel):
    """Schema for sudo token request."""

    username: str
    password: str


class SudoTokenResponse(BaseModel):
    """Schema for sudo token response."""

    sudo_token: str
    expires_in: int


class OAuthSudoTokenRequest(BaseModel):
    """Schema for OAuth sudo token request."""

    access_token: str


class PasswordUpdateRequest(BaseModel):
    """Schema for password update request."""

    password: str
