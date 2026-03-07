import asyncio
import re
import secrets
import string
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from api.apps.user.schemas.auth import LoginResponse, SudoTokenResponse, Token, TokenData
from api.apps.user.schemas.role import RoleData
from api.apps.user.schemas.user import UserCreate, UserData, UserSessionCreate
from api.apps.user.v0.dao.role import RoleDAO, get_role_dao
from api.apps.user.v0.dao.user import UserDAO, get_user_dao
from api.constants import TokenTypes
from api.core.auth import (
    create_access_token,
    create_refresh_token,
    create_sudo_token,
    get_password_hash,
    verify_password,
    verify_token,
)
from api.core.config import settings
from api.core.events import ApplicationEvent, EventNames, event_bus
from api.core.i18n import trans
from api.core.redis import get_redis
from api.utils.date import get_utc_now


class AuthService:
    """Service layer for authentication operations.

    This class handles login, OAuth, token refresh, and session management.
    """

    def __init__(self, user_dao: UserDAO, role_dao: RoleDAO, redis: Redis):
        self._user_dao = user_dao
        self._role_dao = role_dao
        self._redis = redis

    async def _generate_unique_username(self, base_name: str) -> str:
        """
        Generate a unique username from a base name.
        """
        # Simple slugify: lowercase, remove non-alphanumeric, replace spaces with -
        username = re.sub(r"[^a-z0-9]+", "-", base_name.lower()).strip("-")
        if not username:
            username = "user"

        # Check if exists
        if not await self._user_dao.get_by_username(username):
            return username

        # Append random suffix until unique
        attempts = 0
        while True:
            attempts += 1
            if attempts > 100:
                raise ValueError("Could not generate a unique username after 100 attempts.")

            suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
            new_username = f"{username}-{suffix}"
            if not await self._user_dao.get_by_username(new_username):
                return new_username

    async def verify_access_token(self, token: str) -> TokenData:
        """
        Verify access token and return token data.

        Args:
            token: The access token string.
        Returns:
            TokenData: Validated token data.
        """
        return await verify_token(token, self._redis, token_type=TokenTypes.ACCESS.value)

    async def handle_google_oauth(self, user_info: dict) -> UserData:
        """
        Upsert user and identity for Google OAuth.

        Args:
            user_info (dict): Google user info from OAuth callback.
        Returns:
            UserData: The upserted or existing user data.
        """
        # 1. Try to find by Google ID
        user = await self._user_dao.get_by_google_sub(user_info["sub"])
        if user:
            return user

        # 2. Try to find by Email
        email = user_info.get("email")
        if email:
            user = await self._user_dao.get_by_email(email)
            if user:
                # If user exists and Google email is verified, link the account
                if user_info.get("email_verified"):
                    await self._user_dao.add_identity(user.id, user_info)
                    return user
                # If email matches but not verified, we let it fall through to create_user_oauth which will fail
                # with unique constraint error on email, which is safe.

        # 3. Create new user
        base_name = user_info.get("name") or user_info["email"].split("@")[0]
        username = await self._generate_unique_username(base_name)

        user_create = UserCreate(
            username=username,
            email=user_info["email"],
            password=None,
            full_name=user_info.get("name"),
            is_active=True,
        )
        user = await self._user_dao.create_user_oauth(user_create, user_info)
        return user

    async def _get_user_scopes(self, roles: list[RoleData]) -> list[str]:
        if not roles:
            return []

        scopes = set()
        for role in roles:
            for permission in role.permissions:
                scopes.add(permission.name)

        return list(scopes)

    async def authenticate_oauth_user(self, user: UserData, request: Request) -> LoginResponse:
        """
        Issue access and refresh tokens for OAuth user.

        Args:
            user (UserData): The user data.
            request (Request): FastAPI request object.
        Returns:
            LoginResponse: Access and refresh tokens, user data.
        """
        scopes = await self._get_user_scopes(user.roles)
        token_data = {
            "sub": user.username,
            "id": str(user.id),
            "scopes": scopes,
            "token_version": user.token_version,
        }
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

    async def authenticate_user(self, username: str, password: str, request: Request) -> LoginResponse:
        """
        Authenticate user with username and password.

        Args:
            username: User username
            password: User password
            request: FastAPI request object

        Returns:
            LoginResponse: Access and refresh tokens, user data
        """
        user = await self._user_dao.get_by_username(username)
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=trans("auth.invalid_credentials"),
                headers={"WWW-Authenticate": "Bearer"},
            )

        scopes = await self._get_user_scopes(user.roles)
        token_data = {
            "sub": user.username,
            "id": str(user.id),
            "scopes": scopes,
            "token_version": user.token_version,
        }
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

    async def refresh_token(self, refresh_token: str, request: Request) -> LoginResponse:
        """
        Refresh the access token using a refresh token.

        Args:
            refresh_token: The refresh token.
            request: FastAPI request object.

        Returns:
            LoginResponse: A new access token.
        """
        token_data = await verify_token(refresh_token, self._redis, token_type=TokenTypes.REFRESH.value)
        if token_data.id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=trans("auth.invalid_token_data"),
            )
        user = await self._user_dao.get_by_id(token_data.id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=trans("auth.invalid_refresh_user"),
            )

        # Check token version on refresh too?
        if user.token_version != token_data.token_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=trans("auth.token_version_mismatch"),
            )

        scopes = await self._get_user_scopes(user.roles)
        new_token_data = {
            "sub": user.username,
            "id": str(user.id),
            "scopes": scopes,
            "token_version": user.token_version,
        }
        access_token_details = create_access_token(new_token_data)
        new_refresh_token = create_refresh_token(new_token_data)

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
            token=Token(access_token=access_token_details["token"], refresh_token=new_refresh_token),
            user=UserData.model_validate(user),
        )

    async def create_sudo_token_oauth(self, user: UserData) -> SudoTokenResponse:
        """
        Create a sudo token for OAuth user.

        Args:
            user (UserData): The user data.
            request (Request): FastAPI request object.
        Returns:
            SudoTokenResponse: Sudo token with expiration time.
        """
        token_data = {"sub": user.username, "id": str(user.id)}
        sudo_token = create_sudo_token(token_data)
        # Sudo token expires in SUDO_TOKEN_EXPIRE_MINUTES
        return SudoTokenResponse(sudo_token=sudo_token, expires_in=settings.SUDO_TOKEN_EXPIRE_MINUTES * 60)

    async def create_sudo_token_user(self, username: str, password: str) -> SudoTokenResponse:
        """
        Create a sudo token for regular user after password verification.

        Args:
            username: User username
            password: User password
            request (Request): FastAPI request object

        Returns:
            SudoTokenResponse: Sudo token with expiration time
        """
        user = await self._user_dao.get_by_username(username)
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=trans("auth.invalid_credentials"),
                headers={"WWW-Authenticate": "Bearer"},
            )

        token_data = {"sub": user.username, "id": str(user.id)}
        sudo_token = create_sudo_token(token_data)
        # Sudo token expires in SUDO_TOKEN_EXPIRE_MINUTES
        return SudoTokenResponse(sudo_token=sudo_token, expires_in=settings.SUDO_TOKEN_EXPIRE_MINUTES * 60)

    async def revoke_session(self, user_id: UUID, jti: str) -> None:
        """
        Revoke a user session by its JTI.

        Args:
            user_id: The user id
            jti: The JTI of the session to revoke

        Returns:
            None
        """
        ttl = await self._user_dao.revoke_user_session(user_id, jti)
        if ttl is None:
            raise HTTPException(status_code=404, detail=trans("user.session_not_found"))
        await asyncio.gather(
            self._redis.set(f"blacklist:access:{jti}", 1, ex=ttl),
            self._redis.set(f"blacklist:refresh:{jti}", 1, ex=ttl),
        )

    async def update_password(self, user_id: UUID, password: str) -> None:
        """
        Update user password.

        Args:
            user_id: The user id
            password: The new password
        """
        hashed_password = get_password_hash(password)
        await self._user_dao.update_password(user_id, hashed_password)

        user = await self._user_dao.get_by_id(user_id)
        if user:
            # Publish security event
            await event_bus.publish(
                ApplicationEvent(
                    event_name=EventNames.USER_PASSWORD_CHANGED,
                    payload={
                        "user_id": str(user_id),
                        "email": user.email,
                        "username": user.username,
                    },
                )
            )


async def get_auth_service(
    user_dao: UserDAO = Depends(get_user_dao),
    role_dao: RoleDAO = Depends(get_role_dao),
    redis: Redis = Depends(get_redis),
) -> AuthService:
    """
    Dependency to get AuthService instance.

    Args:
        user_dao (UserDAO): The User Data Access Object.
        role_dao (RoleDAO): The Role Data Access Object.
        redis (Redis): The Redis client.

    Returns:
        AuthService: The Auth Service.
    """
    return AuthService(user_dao=user_dao, role_dao=role_dao, redis=redis)
