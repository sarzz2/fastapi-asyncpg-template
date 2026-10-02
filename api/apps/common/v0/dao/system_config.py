from uuid import UUID

from fastapi import Depends

from api.apps.common.v0.schemas.system_config import SystemConfigData, SystemConfigUpdate
from api.core.cache import cache, cache_invalidate
from api.core.database import DataBase, get_db
from api.shared.redis_keys import RedisKeys


class SystemConfigDAO:
    """Data Access Object for system configuration operations."""

    def __init__(self, db: DataBase):
        self.db = db

    @cache(key_pattern=RedisKeys.SYSTEM_CONFIG_CACHE, model=SystemConfigData, expire=86400)
    async def get_config(self) -> SystemConfigData:
        """
        Fetch singleton system configuration.
        """
        query = "SELECT * FROM system_configurations WHERE id = 1;"
        res = await self.db.fetch(query, model=SystemConfigData, fetch_row=True)
        if res is None:
            # Fallback guarantee: seed if missing
            seed_query = (
                "INSERT INTO system_configurations (id) VALUES (1) "
                "ON CONFLICT (id) DO UPDATE SET id = 1 RETURNING *;"
            )
            res = await self.db.write(seed_query, model=SystemConfigData)
        return res

    @cache_invalidate(key_pattern=[RedisKeys.SYSTEM_CONFIG_CACHE])
    async def update_config(self, update_data: SystemConfigUpdate, user_id: UUID | None = None) -> SystemConfigData:
        """
        Update singleton system configuration and invalidate Redis cache.
        """
        query = """
            UPDATE system_configurations
            SET
                enforce_mfa = COALESCE($1, enforce_mfa),
                updated_at = CURRENT_TIMESTAMP,
                updated_by = COALESCE($2, updated_by)
            WHERE id = 1
            RETURNING *;
        """
        return await self.db.write(
            query,
            update_data.enforce_mfa,
            user_id,
            model=SystemConfigData,
        )


def get_system_config_dao(db: DataBase = Depends(get_db)) -> SystemConfigDAO:
    """Dependency provider for SystemConfigDAO."""
    return SystemConfigDAO(db)
