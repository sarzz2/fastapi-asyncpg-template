from typing import List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException

from api.apps.user.schemas.user import UserCreate, UserData, UserSessionCreate, UserSessionData, UserUpdate
from api.constants import OAuthProviders
from api.core.database import DataBase, get_db


class UserDAO:
    """Data Access Object for user-related database operations."""

    def __init__(self, db: DataBase):
        self.db = db

    async def get_by_google_sub(self, sub: str) -> Optional[UserData]:
        """
        Retrieve a user by Google OAuth subject (sub).

        Args:
            sub (str): Google subject identifier.
        Returns:
            Optional[UserData]: User if found, None otherwise.
        """
        query = """
            SELECT u.* FROM users u
             JOIN user_identities i ON u.id = i.user_id
            WHERE i.provider = 'google' AND i.provider_user_id = $1
        """
        return await self.db.fetch(query, sub, model=UserData, fetch_row=True)

    async def create_user_oauth(self, user_data: UserCreate, user_info: dict) -> UserData:
        """
        Create a new user and Google identity in the database.

        Args:
            user_data (UserCreate): User creation data.
            user_info (dict): Google user info from OAuth callback.
        Returns:
            UserData: Created user data.
        """
        user = await self.create_user(user_data, hashed_password=None)
        query = """
            INSERT INTO user_identities (user_id, provider, provider_user_id, email, email_verified, profile)
            VALUES ($1, $2, $3, $4, $5)
        """
        params = (
            user.id,
            OAuthProviders.GOOGLE.value,
            user_info["sub"],
            user_info.get("email"),
            user_info.get("email_verified"),
            user_info,
        )
        await self.db.execute(query, *params)
        return user

    async def get_by_username(self, username: str) -> Optional[UserData]:
        """
        Retrieve a user by username.

        Args:
                db: Database instance for executing queries
                username: Username to search for

        Returns:
                Optional[UserData]: User if found, None otherwise
        """
        query = """
              SELECT * FROM users WHERE username = $1
        """
        # Use database layer's built-in model conversion
        return await self.db.fetch(query, username, model=UserData, fetch_row=True)

    async def get_by_id(self, user_id: UUID) -> Optional[UserData]:
        """
        Retrieve a user by id.

        Args:
            user_id: User id to search for

        Returns:
            Optional[UserData]: User if found, None otherwise
        """
        query = """
              SELECT * FROM users WHERE id = $1
        """
        # Use database layer's built-in model conversion
        return await self.db.fetch(query, user_id, model=UserData, fetch_row=True)

    async def get_by_email(self, email: str) -> Optional[UserData]:
        """
        Retrieve a user by email.

        Args:
            email: Email to search for.
        Returns:
            Optional[UserData]: User if found, None otherwise.
        """
        query = "SELECT * FROM users WHERE email = $1"
        return await self.db.fetch(query, email, model=UserData, fetch_row=True)

    async def add_identity(self, user_id: UUID, user_info: dict) -> None:
        """
        Add a new identity (e.g. Google) to an existing user.

        Args:
            user_id: The ID of the user to link.
            user_info: The identity provider info.
        """
        query = """
            INSERT INTO user_identities (user_id, provider, provider_user_id, email, email_verified, profile)
            VALUES ($1, $2, $3, $4, $5, $6)
        """
        params = (
            user_id,
            OAuthProviders.GOOGLE.value,
            user_info["sub"],
            user_info.get("email"),
            user_info.get("email_verified"),
            user_info,
        )
        await self.db.execute(query, *params)

    async def create_user(
        self,
        user_data: UserCreate,
        hashed_password: Optional[str] = None,
    ) -> UserData:
        """
        Create a new user in the database.

        Args:
                db: Database instance for executing queries
                user_data: User creation data
                hashed_password: Pre-hashed password

        Returns:
                UserData: Created user data
        """
        query = """
			INSERT INTO users (username, email, hashed_password, full_name, is_active)
			VALUES ($1, $2, $3, $4, $5)
			RETURNING *
		"""
        params = (
            user_data.username,
            user_data.email,
            hashed_password,
            user_data.full_name,
            user_data.is_active,
        )
        # Use database layer's built-in model conversion
        return await self.db.write(query, *params, model=UserData)

    async def upsert_user_session(self, user_session_data: UserSessionCreate) -> None:
        """
        Create or update a user session in the database.

        Args:
                db: Database instance for executing queries
                user_session_data: User session creation data

        Returns:
                None
        """
        query = """
               INSERT INTO user_sessions (jti, user_id, issued_at, expires_at, ip_address, user_agent)
                    VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (user_id, user_agent) DO UPDATE
                       SET jti = $1, user_id = $2, issued_at = $3, expires_at = $4, ip_address = $5, updated_at = NOW();
            """
        params = (
            user_session_data.jti,
            user_session_data.user_id,
            user_session_data.issued_at,
            user_session_data.expires_at,
            user_session_data.ip_address,
            user_session_data.user_agent,
        )
        await self.db.write(
            query,
            *params,
            model=UserSessionData,
        )

    async def update_user(self, user_id: UUID, user_update: UserUpdate) -> UserData:
        """
        Update a user in the database.

        Args:
                db: Database instance for executing queries
                user_id: User id to update
                user_update: User update data

        Returns:
                UserData: Updated user data
        """
        query = """
			UPDATE users SET
                email = COALESCE($1, email),
                username = COALESCE($2, username),
                full_name = COALESCE($3, full_name)
            WHERE id = $4
            RETURNING *
		"""
        params = (
            user_update.email,
            user_update.username,
            user_update.full_name,
            user_id,
        )
        return await self.db.write(query, *params, model=UserData)

    async def update_password(self, user_id: UUID, hashed_password: str) -> None:
        """
        Update user password.

        Args:
            user_id: User id to update
            hashed_password: New hashed password
        """
        query = "UPDATE users SET hashed_password = $1 WHERE id = $2"
        await self.db.execute(query, hashed_password, user_id)

    async def revoke_user_session(self, current_user_id: UUID, jti: str) -> int:
        """
        Revoke a user session by its JTI.

        Args:
                db: Database instance for executing queries
                current_user_id: The currently authenticated user id
                jti: The JTI of the session to revoke

        Returns:
                None
        """
        query = """
            DELETE FROM user_sessions
            WHERE jti = $1 AND user_id = $2
            RETURNING (extract(epoch FROM expires_at) - extract(epoch FROM now()))::integer AS ttl;
        """
        row = await self.db.fetchval(query, jti, current_user_id)
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
        return int(row)

    async def get_user_sessions(
        self, user_id: UUID, limit: int, cursor: Optional[UUID] = None
    ) -> List[UserSessionData]:
        """
        Retrieve paginated user sessions.

        Args:
            user_id: The user ID to fetch sessions for.
            limit: The maximum number of sessions to return.
            cursor: The cursor (last session ID) for pagination.

        Returns:
            List[UserSessionData]: List of user sessions.
        """
        if cursor:
            query = """
                SELECT * FROM user_sessions
                WHERE user_id = $1 AND id < $2
                ORDER BY id DESC LIMIT $3
            """
            result = await self.db.fetch(query, user_id, cursor, limit, model=UserSessionData, fetch_row=False)
        else:
            query = """
                SELECT * FROM user_sessions
                WHERE user_id = $1
                ORDER BY id DESC LIMIT $2
            """
            result = await self.db.fetch(query, user_id, limit, model=UserSessionData, fetch_row=False)

        return result if result is not None else []


async def get_user_dao(db: DataBase = Depends(get_db)) -> UserDAO:
    """
    Dependency to get UserDAO instance.
    Args:
        db (DataBase): The database dependency.
    Returns:
        UserDAO: The User Data Access Object.
    """
    return UserDAO(db=db)
