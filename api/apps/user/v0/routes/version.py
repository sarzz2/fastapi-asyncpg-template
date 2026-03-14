from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, Security, status

from api.apps.user.v0.schemas.user import UserData
from api.apps.user.v0.schemas.version import AppVersionData, AppVersionUpdate, ForceUpdateResponse
from api.apps.user.v0.service.version import VersionService, get_version_service
from api.core.dependencies import get_current_user

router = APIRouter()


@router.get("/check", response_model=Optional[ForceUpdateResponse])
async def check_version(
    platform: str, build: int, response: Response, svc: VersionService = Depends(get_version_service)
) -> Optional[ForceUpdateResponse]:
    """
    Check if an update is available or required for the given platform and build.
    Publicly accessible. Returns 426 if update is forced.
    """
    update_info = await svc.check_force_update(platform, build)

    if update_info and update_info.force:
        response.status_code = status.HTTP_426_UPGRADE_REQUIRED

    return update_info


@router.get("/configs", response_model=List[AppVersionData])
async def get_all_version_configs(
    svc: VersionService = Depends(get_version_service),
    _current_user: UserData = Security(get_current_user, scopes=["app:read"]),
) -> List[AppVersionData]:
    """
    Get all version configurations.
    Requires 'app:read' scope.
    """
    return await svc.get_all_versions()


@router.patch("/{platform}", response_model=AppVersionData)
async def update_version_config(
    platform: str,
    update_data: AppVersionUpdate,
    svc: VersionService = Depends(get_version_service),
    _current_user: UserData = Security(get_current_user, scopes=["app:update"]),
) -> AppVersionData:
    """
    Update version configuration for a platform.
    Requires 'app:update' scope.
    """
    info = await svc.update_version_info(platform, update_data)
    if not info:
        raise HTTPException(status_code=404, detail="Platform configuration not found")
    return info
