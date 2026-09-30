import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status

from api.apps.common.constants import API_KEY_LAST_USED_THROTTLE_SECONDS
from api.apps.common.utils import generate_api_key, hash_api_key
from api.apps.common.v0.dao.api_key import ApiKeyDAO, get_api_key_dao
from api.apps.common.v0.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreateInternal,
    ApiKeyCreateResponse,
    ApiKeyData,
    ApiKeyRotateResponse,
    ApiKeyUpdate,
)
from api.core.redis import RedisClient, get_redis
from api.shared.redis_keys import RedisKeys

logger = logging.getLogger("fastapi")


class ApiKeyService:
    """Service layer managing API key lifecycle, cryptographic hashing, and Redis caching."""

    def __init__(self, dao: ApiKeyDAO, redis: RedisClient) -> None:
        self.dao = dao
        self.redis = redis

    async def create_api_key(self, key_in: ApiKeyCreate, created_by: UUID | None = None) -> ApiKeyCreateResponse:
        """
        Create a new API key.

        Args:
            key_in: API key data to create
            created_by: User who created the API key

        Returns:
            ApiKeyCreateResponse: Created API key data
        """
        raw_key, prefix, hashed_key = generate_api_key()

        internal_key = ApiKeyCreateInternal(
            **key_in.model_dump(),
            prefix=prefix,
            hashed_key=hashed_key,
            created_by=created_by,
        )
        api_key_data = await self.dao.create_api_key(internal_key)

        return ApiKeyCreateResponse(
            **api_key_data.model_dump(),
            key=raw_key,
        )

    async def verify_api_key(self, raw_key: str, ip_address: str | None = None) -> ApiKeyData | None:
        """
        Validate API key with Redis caching (delegated to DAO @cache decorator).
        Returns ApiKeyData if valid and active, None otherwise.

        Args:
            raw_key: Raw API key to verify
            ip_address: IP address of the client

        Returns:
            ApiKeyData | None: API key data if valid and active, None otherwise
        """
        if not raw_key:
            return None

        hashed_key = hash_api_key(raw_key)

        api_key_data = await self.dao.get_api_key_by_hash(hashed_key)

        if not api_key_data or not api_key_data.is_active:
            return None

        # Check expiration
        if api_key_data.expires_at:
            now = datetime.now(timezone.utc)
            if api_key_data.expires_at < now:
                return None

        # Throttled update of last_used_at to avoid hammering the database on high traffic
        throttle_lock = f"api_key:last_used_lock:{api_key_data.id}"
        acquired = await self.redis.client.set(throttle_lock, "1", nx=True, ex=API_KEY_LAST_USED_THROTTLE_SECONDS)
        if acquired:
            await self.dao.update_last_used(api_key_data.id, ip_address=ip_address)

        return api_key_data

    async def get_api_key(self, key_id: UUID) -> ApiKeyData:
        """
        Fetch API key metadata by ID.

        Args:
            key_id: ID of the API key to fetch

        Returns:
            ApiKeyData: API key data
        """
        key = await self.dao.get_api_key_by_id(key_id)
        if not key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"API Key with ID '{key_id}' not found.",
            )
        return key

    async def list_api_keys(self, limit: int, cursor: str | None = None) -> list[ApiKeyData]:
        """
        List API keys.

        Args:
            limit: Maximum number of API keys to return
            cursor: Cursor for pagination

        Returns:
            list[ApiKeyData]: List of API keys
        """
        return await self.dao.list_api_keys(limit=limit, cursor=cursor)

    async def _evict_cache(self, hashed_key: str | None) -> None:
        """Evict cached API key from Redis."""
        if hashed_key:
            cache_key = RedisKeys.API_KEY_CACHE.format(hashed_key=hashed_key)
            await self.redis.client.delete(cache_key)

    async def update_api_key(self, key_id: UUID, update_in: ApiKeyUpdate) -> ApiKeyData:
        """
        Update an API key.

        Args:
            key_id: ID of the API key to update
            update_in: API key data to update

        Returns:
            ApiKeyData: Updated API key data
        """
        existing = await self.get_api_key(key_id)
        updated = await self.dao.update_api_key(key_id, update_in)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"API Key with ID '{key_id}' not found.",
            )
        await self._evict_cache(existing.hashed_key)
        return updated

    async def rotate_api_key(self, key_id: UUID) -> ApiKeyRotateResponse:
        """
        Rotate secret for an existing API key.

        Args:
            key_id: ID of the API key to rotate

        Returns:
            ApiKeyRotateResponse: Rotated API key data
        """
        existing = await self.get_api_key(key_id)
        raw_key, prefix, new_hashed_key = generate_api_key()
        updated = await self.dao.rotate_api_key(key_id, new_prefix=prefix, new_hashed_key=new_hashed_key)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Failed to rotate API Key '{key_id}'.",
            )
        await self._evict_cache(existing.hashed_key)
        return ApiKeyRotateResponse(**updated.model_dump(), key=raw_key)

    async def delete_api_key(self, key_id: UUID) -> None:
        """
        Delete an API key.

        Args:
            key_id: ID of the API key to delete

        Returns:
            None
        """
        existing = await self.get_api_key(key_id)
        deleted = await self.dao.delete_api_key(key_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Failed to delete API Key '{key_id}'.",
            )
        await self._evict_cache(existing.hashed_key)


async def get_api_key_service(
    dao: ApiKeyDAO = Depends(get_api_key_dao),
    redis: RedisClient = Depends(get_redis),
) -> ApiKeyService:
    """FastAPI dependency for ApiKeyService."""
    return ApiKeyService(dao=dao, redis=redis)
