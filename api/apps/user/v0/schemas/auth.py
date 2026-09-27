from uuid import UUID

from pydantic import BaseModel

from api.apps.user.v0.schemas.user import UserData
from api.utils.pydantic_utils import StrongPassword


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
    id: UUID | None = None
    exp: int
    jti: str
    type: str = "Bearer"
    scopes: list[str] = []
    token_version: int = 1


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

    password: StrongPassword


class TwoFactorSetupResponse(BaseModel):
    """Response returned when initiating 2FA setup."""

    secret: str
    qr_code: str
    otpauth_url: str


class TwoFactorConfirmRequest(BaseModel):
    """Request payload to confirm and activate 2FA."""

    code: str


class TwoFactorConfirmResponse(BaseModel):
    """Response returned upon successfully activating 2FA."""

    status: str = "enabled"
    backup_codes: list[str]


class TwoFactorStatusResponse(BaseModel):
    """Response showing current 2FA state for a user."""

    is_enabled: bool
    backup_codes_remaining: int


class TwoFactorChallengeResponse(BaseModel):
    """Response returned when user password is correct but 2FA is required."""

    requires_2fa: bool = True
    two_factor_token: str
    token_type: str = "Bearer"


class TwoFactorVerifyRequest(BaseModel):
    """Request payload to complete 2FA login challenge."""

    two_factor_token: str
    code: str
