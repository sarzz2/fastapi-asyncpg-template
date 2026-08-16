from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PermissionBase(BaseModel):
    """Base Permission schema."""

    name: str
    description: str | None = None


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
    description: str | None = None


class RoleCreate(RoleBase):
    """Schema for creating a role."""

    permission_ids: list[UUID] = []


class RoleUpdate(BaseModel):
    """Schema for updating a role."""

    name: str | None = None
    description: str | None = None
    permission_ids: list[UUID] | None = None


class RoleData(RoleBase):
    """Schema for role data in responses."""

    id: UUID
    created_at: datetime
    updated_at: datetime
    permissions: list[PermissionData] = []

    model_config = ConfigDict(from_attributes=True)
