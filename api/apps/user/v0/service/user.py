import asyncio
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from api.apps.user.schemas.user import (
    LoginResponse,
    Token,
    UserCreate,
    UserData,
    UserLogin,
    UserSessionCreate,
    UserUpdate,
)
from api.apps.user.v0.dao.user import UserDAO, get_user_dao
from api.constants import TokenTypes
from api.core.auth import create_access_token, create_refresh_token, get_password_hash, verify_password, verify_token
from api.core.redis import get_redis
from api.utils.date import get_utc_now


class UserService:
    """Service layer for user operations.

    This class expects a `UserDAO` to be injected. FastAPI will construct the
    DAO (and the DAO will obtain a database via its own Depends(get_db)).
    """

    def __init__(self, user_dao: UserDAO, redis: Redis):
        self._user_dao = user_dao
        self._redis = redis

    async def create_user(self, user_in: UserCreate) -> UserData:
        """
        Create a new user and return a response model.

        Args:
            user_in: User creation data

        Returns:
            UserResponse: Created user data
        """
        hashed_password = get_password_hash(user_in.password)
        user_db = await self._user_dao.create_user(user_in, hashed_password)
        return UserData.model_validate(user_db)

    async def authenticate_user(self, login_data: UserLogin, request: Request) -> LoginResponse:
        """
        Authenticate user and return an access token.

        Args:
            login_data: User login credentials
            request: FastAPI request object

        Returns:
            Token: Authentication token
        """
        user = await self._user_dao.get_by_username(login_data.username)
        if not user or not verify_password(login_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token_data = {"sub": user.username, "id": str(user.id)}
        access_token_details = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        await self._user_dao.upsert_user_session(
            user_session_data=UserSessionCreate(
                jti=access_token_details["jti"],
                user_id=user.id,
                issued_at=get_utc_now(),
                expires_at=access_token_details["expires_at"],
                ip_address=request.client.host if request.client is not None else None,
                user_agent=request.headers.get("user-agent"),
            )
        )
        return LoginResponse(
            token=Token(access_token=access_token_details["token"], refresh_token=refresh_token),
            user=UserData.model_validate(user),
        )

    async def get_user_by_username(self, username: str) -> UserData:
        """
        Retrieve a user by username.

        Args:
            username: Username to search for

        Returns:
            UserResponse: User data
        """
        user_db = await self._user_dao.get_by_username(username)
        if not user_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        return UserData.model_validate(user_db)

    async def update_user(self, user_id: UUID, user_update: UserUpdate) -> UserData:
        """
        Update a user by id.

        Args:
            user_id: User id to update
            user_update: User update data

        Returns:
            UserResponse: Updated user data
        """
        user_db = await self._user_dao.update_user(user_id, user_update)
        return UserData.model_validate(user_db)

    async def revoke_user_session(self, current_user_id: UUID, jti: str) -> None:
        """
        Revoke a user session by its JTI.

        Args:
            current_user_id: The currently authenticated user id
            jti: The JTI of the session to revoke

        Returns:
            None
        """
        ttl = await self._user_dao.revoke_user_session(current_user_id, jti)
        await asyncio.gather(
            self._redis.set(f"blacklist:access:{jti}", 1, ex=ttl),
            self._redis.set(f"blacklist:refresh:{jti}", 1, ex=ttl),
        )

    async def refresh_token(self, refresh_token: str, request: Request) -> Token:
        """
        Refresh the access token using a refresh token.

        Args:
            refresh_token: The refresh token.
            request: FastAPI request object.

        Returns:
            A new access token.
        """
        token_data = await verify_token(refresh_token, token_type=TokenTypes.REFRESH.value)
        user = await self.get_user_by_username(token_data.username)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user from refresh token",
            )

        new_token_data = {"sub": user.username, "id": str(user.id)}
        access_token_details = create_access_token(new_token_data)
        refresh_token = create_refresh_token(new_token_data)

        await self._user_dao.upsert_user_session(
            user_session_data=UserSessionCreate(
                jti=access_token_details["jti"],
                user_id=user.id,
                issued_at=get_utc_now(),
                expires_at=access_token_details["expires_at"],
                ip_address=request.client.host if request.client is not None else None,
                user_agent=request.headers.get("user-agent"),
            )
        )

        new_access_token = access_token_details["token"]
        return Token(access_token=new_access_token, refresh_token=refresh_token)


async def get_user_service(user_dao: UserDAO = Depends(get_user_dao), redis: Redis = Depends(get_redis)) -> UserService:
    """
    Dependency to get UserService instance.
    Args:
        user_dao (UserDAO): The User Data Access Object.
    Returns:
        UserService: The User Service.
    """
    return UserService(user_dao=user_dao, redis=redis)
