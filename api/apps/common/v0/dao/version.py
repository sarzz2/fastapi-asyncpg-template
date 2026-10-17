from typing import Any

from fastapi import Depends

from api.apps.common.v0.schemas.version import AppVersionData, AppVersionUpdate
from api.core.cache import cache, cache_invalidate
from api.core.database import DataBase, get_db
from api.core.redis import redis_client
from api.shared.redis_keys import RedisKeys


class VersionDAO:
    """Data Access Object for app version-related database operations."""

    def __init__(self, db: DataBase):
        """Initialize the VersionDAO with a database connection."""
        self.db = db

    @cache(key_pattern=RedisKeys.APP_VERSION_CACHE, model=AppVersionData, expire=None)
    async def get_version_info(self, platform: str) -> AppVersionData | None:
        """
        Fetch version info for a specific platform.
        """
        query = "SELECT * FROM app_versions WHERE platform = $1"
        return await self.db.fetch(query, platform.lower(), model=AppVersionData, fetch_row=True)

    @cache(key_pattern=RedisKeys.APP_VERSIONS_ALL_CACHE, model=AppVersionData, expire=None)
    async def get_all_versions(self) -> list[AppVersionData]:
        """
        Fetch all version configurations.
        """
        query = "SELECT * FROM app_versions ORDER BY platform"
        return await self.db.fetch(query, model=AppVersionData, fetch_row=False)

    async def list_versions(
        self,
        limit: int = 100,
        skip: int = 0,
        search: str | None = None,
    ) -> list[AppVersionData]:
        """
        Retrieve paginated list of app version configurations with optional search.
        """
        if search and search.strip():
            query = """
                SELECT * FROM app_versions
                WHERE LOWER(platform) ILIKE $1
                ORDER BY platform LIMIT $2 OFFSET $3;
            """
            records = await self.db.fetch(
                query,
                f"%{search.strip().lower()}%",
                limit,
                skip,
                model=AppVersionData,
                fetch_row=False,
            )
        else:
            query = "SELECT * FROM app_versions ORDER BY platform LIMIT $1 OFFSET $2;"
            records = await self.db.fetch(query, limit, skip, model=AppVersionData, fetch_row=False)
        return records or []

    async def count_versions(self, search: str | None = None) -> int:
        """
        Count total number of app version records with optional search.
        """
        if search and search.strip():
            val = await self.db.fetchval(
                "SELECT COUNT(*) FROM app_versions WHERE LOWER(platform) ILIKE $1;",
                f"%{search.strip().lower()}%",
            )
        else:
            val = await self.db.fetchval("SELECT COUNT(*) FROM app_versions;")
        return int(val) if val else 0

    async def get_by_platforms(self, platforms: list[str]) -> list[AppVersionData]:
        """
        Retrieve multiple app versions by platform primary keys in a single bulk query.
        """
        if not platforms:
            return []
        lower_platforms = [str(p).lower() for p in platforms]
        query = "SELECT * FROM app_versions WHERE platform = ANY($1::varchar[]) ORDER BY platform;"
        records = await self.db.fetch(query, lower_platforms, model=AppVersionData, fetch_row=False)
        return records or []

    @cache_invalidate(key_pattern=[RedisKeys.APP_VERSIONS_ALL_CACHE])
    async def create_version(self, data: dict[str, Any]) -> AppVersionData:
        """
        Create a new platform app version configuration and invalidate Redis cache.
        """
        platform = str(data["platform"]).lower()
        query = """
            INSERT INTO app_versions (platform, min_build, latest_build, force_update, update_message, update_url)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *;
        """
        result = await self.db.write(
            query,
            platform,
            data["min_build"],
            data["latest_build"],
            data.get("force_update", False),
            data.get("update_message"),
            data.get("update_url"),
            model=AppVersionData,
        )
        await redis_client.client.delete(RedisKeys.APP_VERSION_CACHE.format(platform=platform))
        return result

    @cache_invalidate(key_pattern=[RedisKeys.APP_VERSIONS_ALL_CACHE])
    async def delete_versions(self, platforms: list[str]) -> int:
        """
        Delete app versions by primary keys and invalidate Redis cache.
        """
        if not platforms:
            return 0
        lower_platforms = [str(p).lower() for p in platforms]
        query = "DELETE FROM app_versions WHERE platform = ANY($1::varchar[]) RETURNING platform;"
        rows = await self.db.fetch(query, lower_platforms, fetch_row=False)
        deleted_count = len(rows) if rows else 0
        if deleted_count > 0:
            keys_to_del = [RedisKeys.APP_VERSION_CACHE.format(platform=p) for p in lower_platforms]
            await redis_client.client.delete(*keys_to_del)
        return deleted_count

    @cache_invalidate(key_pattern=[RedisKeys.APP_VERSION_CACHE, RedisKeys.APP_VERSIONS_ALL_CACHE])
    async def update_version_info(self, platform: str, update_data: AppVersionUpdate) -> AppVersionData | None:
        """
        Update version info for a platform and invalidate cache.
        Uses a static query with COALESCE to avoid dynamic SQL construction.
        """
        query = """
            UPDATE app_versions
            SET
                min_build = COALESCE($2, min_build),
                latest_build = COALESCE($3, latest_build),
                force_update = COALESCE($4, force_update),
                update_message = COALESCE($5, update_message),
                update_url = COALESCE($6, update_url),
                updated_at = CURRENT_TIMESTAMP
            WHERE platform = $1
            RETURNING *
        """

        return await self.db.write(
            query,
            platform.lower(),
            update_data.min_build,
            update_data.latest_build,
            update_data.force_update,
            update_data.update_message,
            update_data.update_url,
            model=AppVersionData,
        )


async def get_version_dao(db: DataBase = Depends(get_db)) -> VersionDAO:
    """Dependency to get VersionDAO."""
    return VersionDAO(db=db)
