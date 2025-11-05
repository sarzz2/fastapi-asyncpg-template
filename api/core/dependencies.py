from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from redis.asyncio import Redis
from starlette import status

#
# from app.core.auth import verify_token
from api.apps.user.schemas.user import UserResponse
from api.apps.user.v0.service.user import UserService, get_user_service
from api.core.auth import verify_token
from api.core.redis import RedisClient

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v0/users/login")
redis_client = RedisClient()


credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)
# query = """
#        INSERT INTO sessions (jti, user_id, issued_at, expires_at, ip_address, user_agent)
#             VALUES ($1, $2, $3, $4, $5, $6)
#        ON CONFLICT (user_id, user_agent) DO UPDATE
#                SET jti = $1, user_id = $2, issued_at = $3, expires_at = $4, ip_address = $5, updated_at = NOW();
#     """


async def get_current_user(
    token: str = Depends(oauth2_scheme), user_service: UserService = Depends(get_user_service)
) -> UserResponse:
    """
    Dependency to get the currently authenticated user.
    Args:
        token (str): The JWT token from the request header.
        dao (UserDAO): The User Data Access Object.
    Returns:
        UserResponse: The currently authenticated user.
    """
    token_data = await verify_token(token)
    user = await user_service.get_user_by_username(token_data.username)
    if user is None:
        raise credentials_exception
    return user


async def get_sudo_user(
    token: str = Depends(oauth2_scheme), user_service: UserService = Depends(get_user_service)
) -> UserResponse:
    """
    Dependency to get the currently authenticated sudo user.
    Args:
        token (str): The JWT token from the request header.
        dao (UserDAO): The User Data Access Object.
    Returns:
        UserResponse: The currently authenticated sudo user.
    """
    try:
        token_data = await verify_token(token, "sudo")
        user = await user_service.get_user_by_username(token_data.username)
        if user is None:
            raise credentials_exception
        if token_data.type != "sudo":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sudo access required",
            )
        return user
    except JWTError as exc:
        raise credentials_exception from exc


async def get_redis() -> Redis:
    """Dependency to get the Redis client."""
    return redis_client.client
