import asyncio
from uuid import UUID

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis

from api.apps.user.schemas.user import (
    UserCreate,
    UserData,
    UserUpdate,
)
from api.apps.user.v0.dao.user import UserDAO, get_user_dao
from api.core.auth import get_password_hash
from api.core.redis import get_redis


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
            UserData: Created user data
        """
        if user_in.password is None:
            raise ValueError("Password is required for user creation")
        hashed_password = get_password_hash(user_in.password)
        user_db = await self._user_dao.create_user(user_in, hashed_password)
        return UserData.model_validate(user_db)

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


async def get_user_service(user_dao: UserDAO = Depends(get_user_dao), redis: Redis = Depends(get_redis)) -> UserService:
    """
    Dependency to get UserService instance.
    Args:
        user_dao (UserDAO): The User Data Access Object.
    Returns:
        UserService: The User Service.
    """
    return UserService(user_dao=user_dao, redis=redis)
