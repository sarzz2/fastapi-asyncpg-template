import asyncio
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis

from api.apps.user.v0.dao.user import UserDAO, get_user_dao
from api.apps.user.v0.schemas.user import UserCreate, UserData, UserSessionData, UserUpdate
from api.core.auth import get_password_hash
from api.core.events import ApplicationEvent, EventNames, event_bus
from api.core.i18n import trans
from api.core.redis import get_redis
from api.schemas.pagination import CursorPage


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

        # Dispatch welcome email asynchronously
        await event_bus.publish(
            ApplicationEvent(
                event_name=EventNames.USER_CREATED,
                payload={
                    "user_id": str(user_db.id),
                    "email": user_db.email,
                    "username": user_db.username,
                },
            )
        )

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
                detail=trans("user.not_found"),
            )
        return UserData.model_validate(user_db)

    async def get_user_by_id(self, user_id: UUID) -> UserData:
        """
        Retrieve a user by id.

        Args:
            user_id: User id to search for

        Returns:
            UserResponse: User data
        """
        user_db = await self._user_dao.get_by_id(user_id)
        if not user_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=trans("user.not_found"),
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
        if ttl is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=trans("session.not_found"),
            )
        await asyncio.gather(
            self._redis.set(f"blacklist:access:{jti}", 1, ex=ttl),
            self._redis.set(f"blacklist:refresh:{jti}", 1, ex=ttl),
        )

    async def revoke_all_user_sessions(self, current_user_id: UUID) -> None:
        """
        Revoke all user sessions.

        Args:
            current_user_id: The currently authenticated user id

        Returns:
            None
        """
        revoked_sessions = await self._user_dao.revoke_all_user_sessions(current_user_id)
        if not revoked_sessions:
            return

        redis_tasks = []
        for session in revoked_sessions:
            jti = session["jti"]
            ttl = session["ttl"]
            if ttl is not None and ttl > 0:
                redis_tasks.extend(
                    [
                        self._redis.set(f"blacklist:access:{jti}", 1, ex=ttl),
                        self._redis.set(f"blacklist:refresh:{jti}", 1, ex=ttl),
                    ]
                )

        if redis_tasks:
            await asyncio.gather(*redis_tasks)

    async def get_user_sessions(
        self, user_id: UUID, limit: int = 10, cursor: Optional[UUID] = None
    ) -> CursorPage[UserSessionData]:
        """
        Get paginated user sessions.

        Args:
            user_id: The user ID
            limit: Number of items to return
            cursor: The cursor (last session ID)

        Returns:
            CursorPage[UserSessionData]: Paginated sessions
        """
        # Fetch one more than limit to check if there is a next page
        sessions = await self._user_dao.get_user_sessions(user_id, limit + 1, cursor)

        next_cursor = None

        if len(sessions) > limit:
            sessions = sessions[:limit]
            next_cursor = str(sessions[-1].id)

        return CursorPage(
            items=sessions,
            next_cursor=next_cursor,
        )

    async def assign_roles_to_user(self, user_id: UUID, role_ids: list[UUID]) -> None:
        """
        Assign roles to a user.
        Args:
            user_id: User ID.
            role_ids: List of Role IDs.
        """
        await self._user_dao.assign_roles(user_id, role_ids)


async def get_user_service(user_dao: UserDAO = Depends(get_user_dao), redis: Redis = Depends(get_redis)) -> UserService:
    """
    Dependency to get UserService instance.
    Args:
        user_dao (UserDAO): The User Data Access Object.
    Returns:
        UserService: The User Service.
    """
    return UserService(user_dao=user_dao, redis=redis)
