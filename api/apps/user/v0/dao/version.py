from fastapi import Depends

from api.apps.user.v0.schemas.version import AppVersionData, AppVersionUpdate
from api.core.cache import cache, cache_invalidate
from api.core.database import DataBase, get_db
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
