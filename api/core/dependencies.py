from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from redis.asyncio import Redis
from starlette import status

#
# from app.core.auth import verify_token
from api.apps.user.schemas.user import UserData
from api.apps.user.v0.service.user import UserService, get_user_service
from api.core.auth import verify_token
from api.core.redis import get_redis

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v0/users/login")


credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    user_service: UserService = Depends(get_user_service),
    redis: Redis = Depends(get_redis),
) -> UserData:
    """
    Dependency to get the currently authenticated user.
    Args:
        token (str): The JWT token from the request header.
        dao (UserDAO): The User Data Access Object.
    Returns:
        UserResponse: The currently authenticated user.
    """
    token_data = await verify_token(token, redis)
    if token_data.id is None:
        raise credentials_exception
    user = await user_service.get_user_by_id(token_data.id)
    if user is None:
        raise credentials_exception
    return user


async def get_sudo_user(
    token: str = Depends(oauth2_scheme),
    user_service: UserService = Depends(get_user_service),
    redis: Redis = Depends(get_redis),
) -> UserData:
    """
    Dependency to get the currently authenticated sudo user.
    Args:
        token (str): The JWT token from the request header.
        dao (UserDAO): The User Data Access Object.
    Returns:
        UserResponse: The currently authenticated sudo user.
    """
    try:
        token_data = await verify_token(token, redis, "sudo")
        if token_data.id is None:
            raise credentials_exception
        user = await user_service.get_user_by_id(token_data.id)
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
