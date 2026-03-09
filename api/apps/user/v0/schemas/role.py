from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PermissionBase(BaseModel):
    """Base Permission schema."""

    name: str
    description: Optional[str] = None


class PermissionCreate(PermissionBase):
    """Schema for creating a permission. Inherits all fields from PermissionBase."""


class PermissionData(PermissionBase):
    """Schema for permission data in responses."""

    id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    """Base Role schema."""

    name: str
    description: Optional[str] = None


class RoleCreate(RoleBase):
    """Schema for creating a role."""

    permission_ids: List[UUID] = []


class RoleUpdate(BaseModel):
    """Schema for updating a role."""

    name: Optional[str] = None
    description: Optional[str] = None
    permission_ids: Optional[List[UUID]] = None


class RoleData(RoleBase):
    """Schema for role data in responses."""

    id: UUID
    created_at: datetime
    updated_at: datetime
    permissions: List[PermissionData] = []

    model_config = ConfigDict(from_attributes=True)
