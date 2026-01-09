from typing import List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status

from api.apps.user.schemas.role import PermissionData, RoleCreate, RoleData, RoleUpdate
from api.apps.user.v0.dao.role import RoleDAO, get_role_dao
from api.core.i18n import trans


class RoleService:
    """Service for role-related business logic."""

    def __init__(self, role_dao: RoleDAO):
        self.role_dao = role_dao

    async def get_all_roles(self, limit: int = 20, cursor: Optional[UUID] = None) -> List[RoleData]:
        """
        Get all roles.
        Args:
            limit: Limit the number of roles.
            cursor: Cursor for pagination.
        Returns:
            List[RoleData]: List of roles.
        """
        return await self.role_dao.get_all_roles(limit=limit, cursor=cursor)

    async def get_role_by_id(self, role_id: UUID) -> RoleData:
        """
        Get role by ID.
        Args:
            role_id: ID of the role to retrieve.
        Returns:
            RoleData: The role data.
        Raises:
            HTTPException: If the role is not found.
        """
        role = await self.role_dao.get_role_by_id(role_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=trans("role.not_found"))
        return role

    async def create_role(self, role_create: RoleCreate) -> RoleData:
        """
        Create a new role.
        Args:
            role_create: Data for creating a new role.
        Returns:
            RoleData: The created role data.
        Raises:
            HTTPException: If a role with the same name already exists.
        """
        existing_role = await self.role_dao.get_role_by_name(role_create.name)
        if existing_role:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=trans("role.exists"))
        return await self.role_dao.create_role(role_create)

    async def update_role(self, role_id: UUID, role_update: RoleUpdate) -> RoleData:
        """
        Update a role.
        Args:
            role_id: ID of the role to update.
            role_update: Data for updating the role.
        Returns:
            RoleData: The updated role data.
        Raises:
            HTTPException: If the role is not found or if a role with the same name already exists.
        """
        # Check if role exists
        await self.get_role_by_id(role_id)

        if role_update.name:
            existing_role = await self.role_dao.get_role_by_name(role_update.name)
            if existing_role and existing_role.id != role_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=trans("role.exists"))

        updated_role = await self.role_dao.update_role(role_id, role_update)
        if not updated_role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=trans("role.not_found"))
        return updated_role

    async def delete_role(self, role_id: UUID) -> None:
        """
        Delete a role.
        Args:
            role_id: ID of the role to delete.
        Raises:
            HTTPException: If the role is not found.
        """
        await self.get_role_by_id(role_id)
        await self.role_dao.delete_role(role_id)

    async def get_all_permissions(self, limit: int = 20, cursor: Optional[UUID] = None) -> List[PermissionData]:
        """
        Get all permissions.
        Args:
            limit: Limit the number of permissions.
            cursor: Cursor for pagination.
        Returns:
            List[PermissionData]: List of all permissions.
        """
        return await self.role_dao.get_all_permissions(limit=limit, cursor=cursor)


async def get_role_service(role_dao: RoleDAO = Depends(get_role_dao)) -> RoleService:
    """
    Dependency to get RoleService.
    """
    return RoleService(role_dao=role_dao)
