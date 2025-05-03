from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from redis.asyncio import Redis
from starlette import status

from app.core.auth import verify_token
from app.core.redis import RedisClient
from app.services.v0.user_service import get_user

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
redis_client = RedisClient()

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        token_data = await verify_token(token)
        user = await get_user(token_data.id)
        if user is None:
            raise credentials_exception
        return user
    except HTTPException:
        raise credentials_exception


async def get_sudo_user(token: str = Depends(oauth2_scheme)):
    try:
        token_data = await verify_token(token, "sudo")
        user = await get_user(token_data.id)
        if user is None:
            raise credentials_exception
        if not token_data.type == "sudo":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sudo access required",
            )
        return user
    except JWTError:
        raise credentials_exception
    except HTTPException as exc:
        raise exc


async def get_redis() -> Redis:
    return redis_client.client
