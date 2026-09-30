import logging

import jwt
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes
from redis.asyncio import Redis
from starlette import status

from api.apps.common.v0.schemas.api_key import ApiKeyData
from api.apps.common.v0.service.api_key import ApiKeyService, get_api_key_service
from api.apps.user.v0.schemas.user import UserData
from api.apps.user.v0.service.user import UserService, get_user_service
from api.core.auth import verify_token
from api.core.context import CURRENT_ACTOR_ID
from api.core.redis import get_redis

oauth2_scheme = HTTPBearer()

logger = logging.getLogger("fastapi")

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    security_scopes: SecurityScopes,
    token: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
    user_service: UserService = Depends(get_user_service),
    redis: Redis = Depends(get_redis),
) -> UserData:
    """
    Dependency to get the currently authenticated user.
    Args:
        security_scopes (SecurityScopes): The scopes required for the endpoint.
        token (HTTPAuthorizationCredentials): The JWT token from the request header.
        dao (UserDAO): The User Data Access Object.
    Returns:
        UserResponse: The currently authenticated user.
    """
    token_str = token.credentials
    token_data = await verify_token(token_str, redis)
    if token_data.id is None:
        raise credentials_exception

    for scope in security_scopes.scopes:
        if scope not in token_data.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
                headers={"WWW-Authenticate": f'Bearer scope="{security_scopes.scope_str}"'},
            )

    user = await user_service.get_user_by_id(token_data.id)
    if user is None:
        logger.warning("User not found for valid token: user_id=%s", token_data.id)
        raise credentials_exception
    if user.token_version != token_data.token_version:
        logger.warning(
            "Token version mismatch for user %s. Token: %s, DB: %s",
            user.id,
            token_data.token_version,
            user.token_version,
        )
        raise credentials_exception
    CURRENT_ACTOR_ID.set(str(user.id))
    return user


async def get_sudo_user(
    token: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
    user_service: UserService = Depends(get_user_service),
    redis: Redis = Depends(get_redis),
) -> UserData:
    """
    Dependency to get the currently authenticated sudo user.
    Args:
        token (HTTPAuthorizationCredentials): The JWT token from the request header.
        dao (UserDAO): The User Data Access Object.
    Returns:
        UserResponse: The currently authenticated sudo user.
    """
    try:
        token_str = token.credentials
        token_data = await verify_token(token_str, redis, "sudo")
        if token_data.id is None:
            raise credentials_exception
        user = await user_service.get_user_by_id(token_data.id)
        if user is None:
            logger.warning("Sudo user not found for valid token: user_id=%s", token_data.id)
            raise credentials_exception
        if token_data.type != "sudo":
            logger.warning("Invalid token type for sudo access: %s", token_data.type)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sudo access required",
            )
        CURRENT_ACTOR_ID.set(str(user.id))
        return user
    except jwt.PyJWTError as exc:
        logger.warning("JWT error during sudo verification: %s", exc)
        raise credentials_exception from exc


api_key_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key(
    security_scopes: SecurityScopes,
    raw_key: str | None = Security(api_key_header_scheme),
    service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKeyData:
    """
    Dedicated dependency to validate programmatic API Keys via the X-API-Key header.
    Validates cryptographic hash against Redis cache (or DB fallback), expiration,
    is_active status, and required security scopes.
    Args:
        raw_key (str | None): The raw API key from the request header.
        service (ApiKeyService): The ApiKeyService instance.
    Returns:
        ApiKeyData: The API key data.
    """
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key header (X-API-Key)",
        )

    api_key_data = await service.verify_api_key(raw_key)
    if not api_key_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or inactive API key",
        )

    for scope in security_scopes.scopes:
        if scope not in api_key_data.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not enough permissions: scope '{scope}' required",
            )

    actor_id = api_key_data.created_by or api_key_data.id
    CURRENT_ACTOR_ID.set(str(actor_id))
    return api_key_data
