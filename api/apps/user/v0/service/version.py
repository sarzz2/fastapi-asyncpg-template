import logging

from fastapi import Depends

from api.apps.user.v0.dao.version import VersionDAO, get_version_dao
from api.apps.user.v0.schemas.version import AppVersionData, AppVersionUpdate, ForceUpdateResponse

logger = logging.getLogger("fastapi")


class VersionService:
    """
    Service for version management business logic.
    """

    def __init__(self, version_dao: VersionDAO):
        self.version_dao = version_dao

    async def get_version_info(self, platform: str) -> AppVersionData | None:
        """
        Fetch version info for a specific platform.
        """
        return await self.version_dao.get_version_info(platform=platform)

    async def check_force_update(self, platform: str, build_num: int) -> ForceUpdateResponse | None:
        """
        Check if a force update is required for the given platform and build number.
        """
        if not platform or build_num is None:
            return None

        version_info = await self.get_version_info(platform=platform)
        if not version_info:
            return None

        min_build = version_info.min_build
        latest_build = version_info.latest_build
        force_update = version_info.force_update

        if build_num < min_build:
            logger.warning(
                "VersionService: Force update required for platform=%s, build=%s (min_build=%s)",
                platform,
                build_num,
                min_build,
            )
            return ForceUpdateResponse(
                update_required=True,
                force=True,
                message=version_info.update_message or "A critical update is required.",
                latest_build=latest_build,
                min_build=min_build,
                update_url=version_info.update_url,
            )

        if build_num < latest_build:
            logger.info(
                "VersionService: Optional update available for platform=%s, build=%s (latest_build=%s, force=%s)",
                platform,
                build_num,
                latest_build,
                force_update,
            )
            return ForceUpdateResponse(
                update_required=True,
                force=force_update,
                message=version_info.update_message or "A new version is available.",
                latest_build=latest_build,
                min_build=min_build,
                update_url=version_info.update_url,
            )

        return None

    async def get_all_versions(self) -> list[AppVersionData]:
        """
        Fetch all version configurations.
        """
        return await self.version_dao.get_all_versions()

    async def update_version_info(self, platform: str, update_data: AppVersionUpdate) -> AppVersionData | None:
        """
        Update version info for a platform.
        """
        updated = await self.version_dao.update_version_info(platform, update_data)
        if updated:
            logger.info("VersionService: Updated version configuration for platform=%s", platform)
        return updated


async def get_version_service(version_dao: VersionDAO = Depends(get_version_dao)) -> VersionService:
    """
    Dependency to get VersionService instance.
    """
    return VersionService(version_dao=version_dao)
