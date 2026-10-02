import logging
from uuid import UUID

from fastapi import Depends

from api.apps.common.v0.dao.system_config import SystemConfigDAO, get_system_config_dao
from api.apps.common.v0.schemas.system_config import SystemConfigData, SystemConfigUpdate
from api.core.events import ApplicationEvent, event_bus

logger = logging.getLogger("fastapi")


class SystemConfigService:
    """Service layer managing application-wide system configurations."""

    def __init__(self, dao: SystemConfigDAO):
        self.dao = dao

    async def get_config(self) -> SystemConfigData:
        """Fetch full system configuration.

        Returns:
            SystemConfigData: Full system configuration.
        """
        return await self.dao.get_config()

    async def update_config(self, update_data: SystemConfigUpdate, user_id: UUID | None = None) -> SystemConfigData:
        """Update system configuration, invalidate cache, and emit event.

        Args:
            update_data (SystemConfigUpdate): Data to update.
            user_id (UUID | None): User ID.

        Returns:
            SystemConfigData: Updated system configuration.
        """
        updated = await self.dao.update_config(update_data, user_id)
        logger.info("System configuration updated by user %s", user_id)

        # Emit event on Redis Streams event bus
        await event_bus.publish(
            ApplicationEvent(
                event_name="system_config.updated",
                payload={"updated_by": str(user_id) if user_id else None},
            )
        )
        return updated


def get_system_config_service(
    dao: SystemConfigDAO = Depends(get_system_config_dao),
) -> SystemConfigService:
    """Dependency provider for SystemConfigService."""
    return SystemConfigService(dao)
