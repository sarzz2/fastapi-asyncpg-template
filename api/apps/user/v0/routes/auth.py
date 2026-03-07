from datetime import datetime, timezone
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis

from api.apps.user.constants import GoogleAuthEndpoints
from api.apps.user.schemas.auth import (
    LoginResponse,
    OAuthSudoTokenRequest,
    PasswordUpdateRequest,
    RefreshTokenRequest,
    SudoTokenRequest,
    SudoTokenResponse,
    UserLogin,
)
from api.apps.user.schemas.user import UserData
from api.apps.user.v0.service.auth import AuthService, get_auth_service
from api.core.config import settings
from api.core.dependencies import get_sudo_user
from api.core.i18n import trans
from api.core.rate_limit import limiter
from api.core.redis import get_redis
from api.shared.redis_keys import RedisKeys

router = APIRouter()


@router.get("/google/login", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
@limiter.limit("5/minute")
async def google_login(request: Request, redis: Redis = Depends(get_redis)) -> RedirectResponse:
    """
    Initiate Google OAuth login flow.

    Args:
        request: FastAPI request object
        redis: Redis client dependency
    Returns:
        RedirectResponse: Redirect to Google OAuth consent screen
    """
    # build redirect uri that Google will callback to
    redirect_uri = str(request.url_for("google_callback"))

    # generate state and store in redis
    state = uuid4().hex
    state_key = RedisKeys.OAUTH_STATE_GOOGLE.format(state=state)
    await redis.set(state_key, "1", ex=300)

    # build auth url
    scope = "openid email profile"
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = httpx.URL(GoogleAuthEndpoints.GOOGLE_AUTH_ENDPOINT).copy_with(params=params)
    return RedirectResponse(url=str(auth_url), status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/google/callback", response_model=LoginResponse)
async def google_callback(
    request: Request,
    svc: AuthService = Depends(get_auth_service),
    redis: Redis = Depends(get_redis),
) -> LoginResponse:
    """
    Google OAuth callback endpoint. Upserts user and identity, returns tokens.

    Args:
        request: FastAPI request object
        svc: Auth service dependency
        redis: Redis client dependency
    Returns:
        LoginResponse: Access and refresh tokens, user data
    """
    # Validate state parameter against Redis
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        raise HTTPException(status_code=400, detail=trans("auth.missing_callback_params"))

    state_key = RedisKeys.OAUTH_STATE_GOOGLE.format(state=state)
    stored = await redis.get(state_key)
    if not stored:
        raise HTTPException(status_code=400, detail=trans("auth.invalid_state"))
    # delete state to prevent replay
    await redis.delete(state_key)

    # Exchange code for tokens
    redirect_uri = str(request.url_for("google_callback"))

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GoogleAuthEndpoints.GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=400, detail=trans("auth.token_exchange_failed").format(error=token_resp.text)
            )
        token = token_resp.json()

        access_token = token.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail=trans("auth.no_access_token"))

        # Fetch userinfo
        userinfo_resp = await client.get(
            GoogleAuthEndpoints.GOOGLE_USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(status_code=400, detail=trans("auth.userinfo_failed"))
        user_info = userinfo_resp.json()

    user = await svc.handle_google_oauth(user_info)
    return await svc.authenticate_oauth_user(user, request)


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    login_data: UserLogin,
    svc: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    """
    Authenticate user and return access token.

    Args:
        request: FastAPI request object
        login_data: User login credentials
        svc: Auth service dependency
    Returns:
        LoginResponse: Authentication token and user data
    """
    return await svc.authenticate_user(login_data.username, login_data.password, request)


@router.post("/refresh", response_model=LoginResponse)
@limiter.limit("5/minute")
async def refresh_access_token(
    request: Request,
    token_request: RefreshTokenRequest,
    svc: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    """
    Refresh access token using a refresh token.

    Args:
        request: The FastAPI request object.
        token_request: The request body containing the refresh token.
        svc: The auth service dependency.
    Returns:
        LoginResponse: A new access token.
    """
    return await svc.refresh_token(token_request.refresh_token, request)


@router.post("/sudo", response_model=SudoTokenResponse)
@limiter.limit("5/minute")
async def create_sudo_token(
    _request: Request,
    sudo_request: SudoTokenRequest,
    svc: AuthService = Depends(get_auth_service),
) -> SudoTokenResponse:
    """
    Create a sudo token for privileged operations using credentials.

    Args:
        request: The FastAPI request object.
        sudo_request: The request body containing username and password.
        svc: The auth service dependency.
    Returns:
        SudoTokenResponse: Sudo token with expiration time.
    """
    return await svc.create_sudo_token_user(sudo_request.username, sudo_request.password)


@router.post("/google/sudo", response_model=SudoTokenResponse)
@limiter.limit("5/minute")
async def google_sudo_token(
    _request: Request,
    sudo_request: OAuthSudoTokenRequest,
    svc: AuthService = Depends(get_auth_service),
) -> SudoTokenResponse:
    """
    Create a sudo token for OAuth (Google) user for privileged operations.

    Args:
        request: The FastAPI request object.
        sudo_request: The request body containing the current access token.
        svc: The auth service dependency.
    Returns:
        SudoTokenResponse: Sudo token with expiration time.
    """
    # For OAuth users, we verify the access token first
    try:
        token_data = await svc.verify_access_token(sudo_request.access_token)
        # Create a temporary UserData object with minimal required fields
        user_data = UserData(
            username=token_data.username,
            id=token_data.id,
            is_active=True,
            hashed_password=None,
            email="",
            full_name=None,
            created_at=datetime.now(timezone.utc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=trans("auth.invalid_access_token"),
        ) from exc
    return await svc.create_sudo_token_oauth(user_data)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def update_password(
    password_update: PasswordUpdateRequest,
    current_user: UserData = Depends(get_sudo_user),
    svc: AuthService = Depends(get_auth_service),
) -> None:
    """
    Update user password. Requires sudo token.

    Args:
        password_update: The new password.
        current_user: The currently authenticated user (via sudo token).
        svc: The auth service dependency.
    """
    await svc.update_password(current_user.id, password_update.password)
