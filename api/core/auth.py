import datetime
from datetime import timedelta
from typing import Optional
from uuid import uuid4

import bcrypt
import jwt
from fastapi import HTTPException, status
from redis.asyncio import Redis

from api.apps.user.schemas.auth import TokenData
from api.constants import TokenTypes

from .config import settings
from .redis import RedisClient

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS
SUDO_TOKEN_EXPIRE_MINUTES = settings.SUDO_TOKEN_EXPIRE_MINUTES
redis_client = RedisClient()


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """
    Verify a plain password against a hashed password.
    Args:
        plain_password (str): The plain text password to verify.
        hashed_password (str): The hashed password to compare against.
    Returns:
        bool: True if the passwords match, False otherwise.
    """
    if hashed_password is None:
        return False
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    """
    Hash a plain password using bcrypt.
    Args:
        password (str): The plain text password to hash.
    Returns:
        str: The hashed password.
    """
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _create_token(data: dict, expire: datetime.datetime, token_type: str) -> dict:
    """
    Create a JWT token.
    Args:
        data (dict): The data to include in the token payload.
        expire (datetime.datetime): The expiration time of the token.
        token_type (str): The type of the token (e.g., "access", "refresh", "sudo").
    Returns:
        dict: A dictionary containing the encoded token and its metadata.
    """
    to_encode = data.copy()
    jti = str(uuid4())
    to_encode.update({"exp": expire, "type": token_type, "jti": jti})
    encoded_token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return {
        "token": encoded_token,
        "expires_at": expire,
        "jti": jti,
    }


def create_access_token(data: dict) -> dict:
    """
    Create an access JWT token.
    Args:
        data (dict): The data to include in the token payload.
    Returns:
        dict: A dictionary containing the encoded token and its metadata.
    """
    expire = datetime.datetime.now(datetime.UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return _create_token(data, expire, token_type=TokenTypes.ACCESS.value)


def create_refresh_token(data: dict) -> str:
    """
    Create a refresh JWT token.
    Args:
        data (dict): The data to include in the token payload.
    Returns:
        str: The encoded refresh JWT token.
    """
    expire = datetime.datetime.now(datetime.UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    token_details = _create_token(data, expire, token_type=TokenTypes.REFRESH.value)
    return str(token_details["token"])


def create_sudo_token(data: dict) -> str:
    """
    Create a sudo JWT token.
    Args:
        data (dict): The data to include in the token payload.
    Returns:
        str: The encoded sudo JWT token.
    """
    expire = datetime.datetime.now(datetime.UTC) + timedelta(minutes=SUDO_TOKEN_EXPIRE_MINUTES)
    token_details = _create_token(data, expire, token_type=TokenTypes.SUDO.value)
    return str(token_details["token"])


async def verify_token(token: str, redis: Redis, token_type: Optional[str] = "access") -> TokenData:
    """
    Verify a JWT token and return the token data.
    Args:
        token (str): The JWT token to verify.
        redis (Redis): The Redis client.
        token_type (Optional[str]): The expected type of the token ("access", "refresh", "sudo").
    Returns:
        TokenData: The data contained in the token.
    Raises:
        HTTPException: If the token is invalid or has been revoked.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        user_id: str = payload.get("id")
        exp: int = payload.get("exp")
        jti: str = payload.get("jti")
        jwt_token_type: str = payload.get("type")
        scopes: list[str] = payload.get("scopes", [])
        token_version: int = payload.get("token_version", 1)

        if user_id is None or payload.get("type") != token_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )

        # Check if the token is blacklisted
        if token_type == TokenTypes.ACCESS.value:
            if await redis.get(f"blacklist:access:{jti}") is not None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Access token has been revoked.",
                )
        elif token_type == TokenTypes.REFRESH.value:
            if await redis.get(f"blacklist:refresh:{jti}") is not None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token has been revoked.",
                )
        elif token_type == TokenTypes.SUDO.value:
            if await redis.get(f"blacklist:sudo:{jti}") is not None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Sudo token has been revoked.",
                )
        return TokenData(
            username=username,
            id=user_id,
            exp=exp,
            jti=jti,
            type=jwt_token_type,
            scopes=scopes,
            token_version=token_version,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        ) from exc
