import datetime
from datetime import timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import HTTPException, status
from pydantic import BaseModel

from .config import settings
from .redis import RedisClient

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS
SUDO_TOKEN_EXPIRE_MINUTES = settings.SUDO_TOKEN_EXPIRE_MINUTES
redis_client = RedisClient()


class TokenData(BaseModel):
    username: str
    id: str
    exp: int
    type: str


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if isinstance(hashed_password, str):
        hashed_password = hashed_password.encode("utf-8")
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password)


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _create_token(data: dict, expire: datetime.datetime, token_type: str) -> str:
    to_encode = data.copy()
    to_encode.update({"exp": expire, "type": token_type})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(data: dict) -> str:
    expire = datetime.datetime.now(datetime.UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return _create_token(data, expire, token_type="access")


def create_refresh_token(data: dict) -> str:
    expire = datetime.datetime.now(datetime.UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return _create_token(data, expire, token_type="refresh")


def create_sudo_token(data: dict) -> str:
    expire = datetime.datetime.now(datetime.UTC) + timedelta(minutes=SUDO_TOKEN_EXPIRE_MINUTES)
    return _create_token(data, expire, token_type="sudo")


async def verify_token(token: str, token_type: Optional[str] = "access") -> TokenData:
    redis = redis_client.client
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        user_id: str = payload.get("id")
        exp: int = payload.get("exp")
        jti: str = payload.get("jti")
        jwt_token_type: str = payload.get("type")
        if user_id is None or payload.get("type") != token_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )

        # Check if the token is blacklisted
        if token_type == "access":
            if await redis.get(f"blacklist:access:{jti}") is not None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token has been revoked.")
        elif token_type == "refresh":
            if await redis.get(f"blacklist:refresh:{jti}") is not None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been revoked.")
        return TokenData(username=username, id=user_id, exp=exp, type=jwt_token_type)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
