import logging

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes
from jose import JWTError
from redis.asyncio import Redis
from starlette import status

from api.apps.user.v0.schemas.user import UserData
from api.apps.user.v0.service.user import UserService, get_user_service
from api.core.auth import verify_token
from api.core.redis import get_redis

oauth2_scheme = HTTPBearer()

log = logging.getLogger("fastapi")

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
        log.warning("User not found for valid token: user_id=%s", token_data.id)
        raise credentials_exception
    if user.token_version != token_data.token_version:
        log.warning(
            "Token version mismatch for user %s. Token: %s, DB: %s",
            user.id,
            token_data.token_version,
            user.token_version,
        )
        raise credentials_exception
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
            log.warning("Sudo user not found for valid token: user_id=%s", token_data.id)
            raise credentials_exception
        if token_data.type != "sudo":
            log.warning("Invalid token type for sudo access: %s", token_data.type)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sudo access required",
            )
        return user
    except JWTError as exc:
        log.warning("JWT error during sudo verification: %s", exc)
        raise credentials_exception from exc
