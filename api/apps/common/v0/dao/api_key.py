from uuid import UUID

from fastapi import Depends

from api.apps.common.constants import API_KEY_CACHE_TTL_SECONDS
from api.apps.common.v0.schemas.api_key import ApiKeyCreateInternal, ApiKeyData, ApiKeyUpdate
from api.core.cache import cache
from api.core.database import DataBase, get_db
from api.shared.redis_keys import RedisKeys


class ApiKeyDAO:
    """Data Access Object for API Key database operations."""

    def __init__(self, db: DataBase) -> None:
        self.db = db

    async def create_api_key(self, key_in: ApiKeyCreateInternal) -> ApiKeyData:
        """
        Create a new API key record.

        Args:
            key_in (ApiKeyCreateInternal): The API key creation schema.

        Returns:
            ApiKeyData: The created API key data.
        """
        query = """
            INSERT INTO api_keys (name, prefix, hashed_key, scopes, rate_limit, expires_at, created_by, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
        """
        return await self.db.write(
            query,
            key_in.name,
            key_in.prefix,
            key_in.hashed_key,
            key_in.scopes,
            key_in.rate_limit,
            key_in.expires_at,
            key_in.created_by,
            key_in.is_active,
            model=ApiKeyData,
        )

    @cache(key_pattern=RedisKeys.API_KEY_CACHE, model=ApiKeyData, expire=API_KEY_CACHE_TTL_SECONDS)
    async def get_api_key_by_hash(self, hashed_key: str) -> ApiKeyData | None:
        """
        Fetch API key by its SHA-256 hash (cached in Redis via @cache).

        Args:
            hashed_key: Hashed key to fetch

        Returns:
            ApiKeyData | None: API key data
        """
        query = """
            SELECT * FROM api_keys
            WHERE hashed_key = $1
        """
        return await self.db.fetch(query, hashed_key, model=ApiKeyData, fetch_row=True)

    async def get_api_key_by_id(self, key_id: UUID) -> ApiKeyData | None:
        """
        Fetch API key by UUID.

        Args:
            key_id: UUID of the API key

        Returns:
            ApiKeyData | None: API key data
        """
        query = "SELECT * FROM api_keys WHERE id = $1"
        return await self.db.fetch(query, key_id, model=ApiKeyData, fetch_row=True)

    async def list_api_keys(
        self,
        limit: int,
        cursor: str | None = None,
    ) -> list[ApiKeyData]:
        """
        List API keys with cursor pagination.

        Args:
            limit: Limit of API keys to fetch
            cursor: Cursor for pagination

        Returns:
            list[ApiKeyData]: List of API key data
        """
        if cursor:
            query = "SELECT * FROM api_keys WHERE id < $1::uuid ORDER BY id DESC LIMIT $2;"
            return await self.db.fetch(query, cursor, limit, model=ApiKeyData, fetch_row=False)
        query = "SELECT * FROM api_keys ORDER BY id DESC LIMIT $1;"
        return await self.db.fetch(query, limit, model=ApiKeyData, fetch_row=False)

    async def update_api_key(self, key_id: UUID, update_data: ApiKeyUpdate) -> ApiKeyData | None:
        """
        Update an existing API key's attributes.

        Args:
            key_id: UUID of the API key
            update_data: Data to update

        Returns:
            ApiKeyData | None: Updated API key data
        """
        query = """
            UPDATE api_keys
            SET
                name = COALESCE($2, name),
                scopes = COALESCE($3, scopes),
                rate_limit = COALESCE($4, rate_limit),
                expires_at = COALESCE($5, expires_at),
                is_active = COALESCE($6, is_active),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            RETURNING *
        """
        return await self.db.write(
            query,
            key_id,
            update_data.name,
            update_data.scopes,
            update_data.rate_limit,
            update_data.expires_at,
            update_data.is_active,
            model=ApiKeyData,
        )

    async def rotate_api_key(self, key_id: UUID, new_prefix: str, new_hashed_key: str) -> ApiKeyData | None:
        """
        Rotate the API key secret and prefix.

        Args:
            key_id: UUID of the API key
            new_prefix: New visible prefix
            new_hashed_key: New SHA-256 hash

        Returns:
            ApiKeyData | None: Rotated API key data
        """
        query = """
            UPDATE api_keys
            SET
                prefix = $2,
                hashed_key = $3,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            RETURNING *
        """
        return await self.db.write(query, key_id, new_prefix, new_hashed_key, model=ApiKeyData)

    async def update_last_used(self, key_id: UUID, ip_address: str | None = None) -> None:
        """
        Update last used timestamp and IP.

        Args:
            key_id: UUID of the API key
            ip_address: IP address of the client
        """
        query = """
            UPDATE api_keys
            SET
                last_used_at = CURRENT_TIMESTAMP,
                last_used_ip = $2::inet
            WHERE id = $1
        """
        await self.db.execute(query, key_id, ip_address)

    async def delete_api_key(self, key_id: UUID) -> bool:
        """
        Hard delete an API key by ID.

        Args:
            key_id: UUID of the API key

        Returns:
            bool: True if API key was deleted, False otherwise
        """
        query = "DELETE FROM api_keys WHERE id = $1"
        res = await self.db.execute(query, key_id)
        return " 0" not in res


async def get_api_key_dao(db: DataBase = Depends(get_db)) -> ApiKeyDAO:
    """
    FastAPI dependency for ApiKeyDAO.

    Args:
        db: Database connection

    Returns:
        ApiKeyDAO: API key DAO instance
    """
    return ApiKeyDAO(db=db)
