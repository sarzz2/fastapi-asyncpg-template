import asyncio
from typing import Any, List, Optional
from uuid import UUID

from fastapi import Depends

from api.apps.user.schemas.user import UserCreate, UserData, UserSessionCreate, UserSessionData, UserUpdate
from api.constants import OAuthProviders
from api.core.database import DataBase, get_db


class UserDAO:
    """Data Access Object for user-related database operations."""

    def __init__(self, db: DataBase):
        self.db = db

    async def _get_user_with_roles(self, where_clause: str, *args: Any) -> Optional[UserData]:
        query = f"""
            SELECT
                u.*,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'id', r.id,
                            'name', r.name,
                            'description', r.description,
                            'created_at', r.created_at,
                            'updated_at', r.updated_at,
                            'permissions', (
                                SELECT COALESCE(json_agg(
                                    json_build_object(
                                        'id', p.id,
                                        'name', p.name,
                                        'description', p.description,
                                        'created_at', p.created_at
                                    )
                                ), '[]')
                                FROM role_permissions rp
                                JOIN permissions p ON rp.permission_id = p.id
                                WHERE rp.role_id = r.id
                            )
                        )
                    ) FILTER (WHERE r.id IS NOT NULL), '[]'
                ) as roles
            FROM users u
            LEFT JOIN user_roles ur ON u.id = ur.user_id
            LEFT JOIN roles r ON ur.role_id = r.id
            WHERE {where_clause}
            GROUP BY u.id
        """  # nosec
        record = await self.db.fetch(query, *args, fetch_row=True)
        return UserData.model_validate(dict(record)) if record else None

    async def get_by_google_sub(self, sub: str) -> Optional[UserData]:
        """
        Retrieve a user by Google OAuth subject (sub).

        Args:
            sub (str): Google subject identifier.
        Returns:
            Optional[UserData]: User if found, None otherwise.
        """
        # For this one, we need to join user_identities as well
        query = """
            SELECT
                u.*,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'id', r.id,
                            'name', r.name,
                            'description', r.description,
                            'created_at', r.created_at,
                            'updated_at', r.updated_at,
                            'permissions', (
                                SELECT COALESCE(json_agg(
                                    json_build_object(
                                        'id', p.id,
                                        'name', p.name,
                                        'description', p.description,
                                        'created_at', p.created_at
                                    )
                                ), '[]')
                                FROM role_permissions rp
                                JOIN permissions p ON rp.permission_id = p.id
                                WHERE rp.role_id = r.id
                            )
                        )
                    ) FILTER (WHERE r.id IS NOT NULL), '[]'
                ) as roles
            FROM users u
            JOIN user_identities i ON u.id = i.user_id
            LEFT JOIN user_roles ur ON u.id = ur.user_id
            LEFT JOIN roles r ON ur.role_id = r.id
            WHERE i.provider = 'google' AND i.provider_user_id = $1
            GROUP BY u.id
        """
        record = await self.db.fetch(query, sub, fetch_row=True)
        return UserData.model_validate(dict(record)) if record else None

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
            VALUES ($1, $2, $3, $4, $5, $6)
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
        return await self._get_user_with_roles("u.username = $1", username)

    async def get_by_id(self, user_id: UUID) -> Optional[UserData]:
        """
        Retrieve a user by id.

        Args:
            user_id: User id to search for

        Returns:
            Optional[UserData]: User if found, None otherwise
        """
        return await self._get_user_with_roles("u.id = $1", user_id)

    async def get_by_email(self, email: str) -> Optional[UserData]:
        """
        Retrieve a user by email.

        Args:
            email: Email to search for.
        Returns:
            Optional[UserData]: User if found, None otherwise.
        """
        return await self._get_user_with_roles("u.email = $1", email)

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

    async def update_user(self, user_id: UUID, user_update: UserUpdate) -> UserData | None:
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
		"""
        params = (
            user_update.email,
            user_update.username,
            user_update.full_name,
            user_id,
        )
        # For update, we re-fetch the user to get role.
        await self.db.execute(query, *params)
        return await self.get_by_id(user_id)

    async def update_password(self, user_id: UUID, hashed_password: str) -> None:
        """
        Update user password.

        Args:
            user_id: User id to update
            hashed_password: New hashed password
        """
        query = "UPDATE users SET hashed_password = $1, token_version = token_version + 1 WHERE id = $2"
        await self.db.execute(query, hashed_password, user_id)

    async def revoke_user_session(self, current_user_id: UUID, jti: str) -> Optional[int]:
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
            return None
        return int(row)

    async def revoke_all_user_sessions(self, current_user_id: UUID) -> List[dict]:
        """
        Revoke all sessions for a user.

        Args:
                current_user_id: The currently authenticated user id

        Returns:
                List[dict]: List of dictionaries containing 'jti' and 'ttl' for each revoked session.
        """
        query = """
            DELETE FROM user_sessions
            WHERE user_id = $1
            RETURNING jti, (extract(epoch FROM expires_at) - extract(epoch FROM now()))::integer AS ttl;
        """
        records = await self.db.fetch(query, current_user_id, fetch_row=False)
        return [dict(record) for record in records] if records else []

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

    async def assign_roles(self, user_id: UUID, role_ids: List[UUID]) -> None:
        """
        Assign roles to a user.
        Args:
            user_id: User ID.
            role_ids: List of Role IDs.
        """
        if not role_ids:
            return

        values = [(user_id, role_id) for role_id in role_ids]
        query = """
        INSERT INTO user_roles (user_id, role_id)
        SELECT * FROM UNNEST($1::uuid[], $2::uuid[])
        ON CONFLICT DO NOTHING
        """
        update_query = "UPDATE users SET token_version = token_version + 1 WHERE id = $1"

        await asyncio.gather(
            self.db.execute(
                query,
                [v[0] for v in values],
                [v[1] for v in values],
            ),
            self.db.execute(update_query, user_id),
        )


async def get_user_dao(db: DataBase = Depends(get_db)) -> UserDAO:
    """
    Dependency to get UserDAO instance.
    Args:
        db (DataBase): The database dependency.
    Returns:
        UserDAO: The User Data Access Object.
    """
    return UserDAO(db=db)
