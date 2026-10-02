from fastapi import APIRouter, Depends, Security

from api.apps.common.v0.schemas.system_config import SystemConfigData, SystemConfigUpdate
from api.apps.common.v0.service.system_config import SystemConfigService, get_system_config_service
from api.apps.user.v0.schemas.user import UserData
from api.core.dependencies import get_current_user

router = APIRouter()


@router.get("", response_model=SystemConfigData)
async def get_system_config(
    svc: SystemConfigService = Depends(get_system_config_service),
    _current_user: UserData = Security(get_current_user, scopes=["system_config:read"]),
) -> SystemConfigData:
    """
    Get full system configuration details.
    Requires 'system_config:read' permission scope.
    """
    return await svc.get_config()


@router.patch("", response_model=SystemConfigData)
async def update_system_config(
    update_data: SystemConfigUpdate,
    svc: SystemConfigService = Depends(get_system_config_service),
    current_user: UserData = Security(get_current_user, scopes=["system_config:update"]),
) -> SystemConfigData:
    """
    Update system configuration.
    Requires 'system_config:update' permission scope.
    """
    return await svc.update_config(update_data, current_user.id)
