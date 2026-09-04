from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Security, status

from api.apps.user.v0.schemas.role import PermissionData, RoleCreate, RoleData, RoleUpdate
from api.apps.user.v0.schemas.user import UserData
from api.apps.user.v0.service.role import RoleService, get_role_service
from api.core.dependencies import get_current_user
from api.utils.pagination import Page, PaginationParams, apply_cursor_pagination

router = APIRouter()


@router.get("/permissions", response_model=Page[PermissionData])
async def get_permissions(
    pagination: Annotated[PaginationParams, Query()],
    service: RoleService = Depends(get_role_service),
    _current_user: UserData = Security(get_current_user, scopes=["roles:read"]),
) -> Page[PermissionData]:
    """
    Get all permissions.
    Requires 'roles:read' scope.
    """
    return await apply_cursor_pagination(
        fetch_func=service.get_all_permissions,
        params=pagination,
        get_cursor_value=lambda x: str(x.id),
    )


@router.get("", response_model=Page[RoleData])
async def get_roles(
    pagination: Annotated[PaginationParams, Query()],
    service: RoleService = Depends(get_role_service),
    _current_user: UserData = Security(get_current_user, scopes=["roles:read"]),
) -> Page[RoleData]:
    """
    Get all roles.
    Requires 'roles:read' scope.
    """
    return await apply_cursor_pagination(
        fetch_func=service.get_all_roles,
        params=pagination,
        get_cursor_value=lambda x: str(x.id),
    )


@router.get("/{role_id}", response_model=RoleData)
async def get_role(
    role_id: UUID,
    service: RoleService = Depends(get_role_service),
    _current_user: UserData = Security(get_current_user, scopes=["roles:read"]),
) -> RoleData:
    """
    Get a role by ID.
    Requires 'roles:read' scope.
    """
    return await service.get_role_by_id(role_id)


@router.post("", response_model=RoleData, status_code=status.HTTP_201_CREATED)
async def create_role(
    role_create: RoleCreate,
    service: RoleService = Depends(get_role_service),
    _current_user: UserData = Security(get_current_user, scopes=["roles:create"]),
) -> RoleData:
    """
    Create a new role.
    Requires 'roles:create' scope.
    """
    return await service.create_role(role_create)


@router.patch("/{role_id}", response_model=RoleData)
async def update_role(
    role_id: UUID,
    role_update: RoleUpdate,
    service: RoleService = Depends(get_role_service),
    _current_user: UserData = Security(get_current_user, scopes=["roles:update"]),
) -> RoleData:
    """
    Update a role.
    Requires 'roles:update' scope.
    """
    return await service.update_role(role_id, role_update)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: UUID,
    service: RoleService = Depends(get_role_service),
    _current_user: UserData = Security(get_current_user, scopes=["roles:delete"]),
) -> None:
    """
    Delete a role.
    Requires 'roles:delete' scope.
    """
    await service.delete_role(role_id)
