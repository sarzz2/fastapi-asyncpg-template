"""
Admin views for the User domain (Roles management).
"""

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette_admin.fields import DateTimeField, StringField, TagsField, TextAreaField, UUIDField
from starlette_admin.filters import FilterGroup

from api.apps.user.v0.dao.role import RoleDAO
from api.apps.user.v0.schemas.role import RoleCreate, RoleData, RoleUpdate
from api.core.database import DataBase
from api.utils.admin_view import BaseAppAdminView


class RoleAdminView(BaseAppAdminView):
    """
    Custom Starlette-Admin view for managing Roles via raw SQL and RoleDAO.
    """

    key = "role"
    identity = "role"
    name = "Role"
    label = "Roles"
    menu_label = "Roles"
    icon = "fa-solid fa-user-shield"
    pk_attr = "id"

    fields = [
        UUIDField("id", label="ID", read_only=True),
        StringField("name", label="Name", required=True),
        TextAreaField("description", label="Description"),
        TagsField("permissions", label="Permissions"),
        DateTimeField("created_at", label="Created At", read_only=True),
        DateTimeField("updated_at", label="Updated At", read_only=True),
    ]

    def __init__(self, db: DataBase) -> None:
        """
        Initialize RoleAdminView with shared DataBase and RoleDAO instances.

        Args:
            db (DataBase): Database connection instance.
        """
        super().__init__()
        self.db = db
        self.dao = RoleDAO(self.db)

    @staticmethod
    def _to_admin_object(role: RoleData) -> SimpleNamespace:
        """
        Dynamically convert a RoleData Pydantic model into a Starlette-Admin compatible object.

        Args:
            role (RoleData): RoleData Pydantic model instance.

        Returns:
            SimpleNamespace: Admin-compatible object with dynamically mapped fields.
        """
        data = role.model_dump()
        if "permissions" in data and isinstance(data["permissions"], list):
            data["permissions"] = [p.get("name") if isinstance(p, dict) else p for p in data["permissions"]]
        return SimpleNamespace(**data)

    async def get_pk_value(self, request: Request, obj: Any) -> Any:
        """
        Extract the primary key value from a role object or dictionary.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            obj (Any): The role data object or dictionary.

        Returns:
            Any: The primary key (ID) value.
        """
        if isinstance(obj, dict):
            return obj.get("id")
        return getattr(obj, "id", None)

    async def find_all(
        self,
        request: Request,
        skip: int = 0,
        limit: int = 100,
        q: str | None = None,
        sorts: Sequence[tuple[str, str]] | None = None,
        filters: FilterGroup | None = None,
    ) -> Sequence[Any]:
        """
        Retrieve paginated list of roles.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            skip (int): Number of records to skip for pagination. Defaults to 0.
            limit (int): Maximum number of records to return. Defaults to 100.
            q (str | None): Optional search query string. Defaults to None.
            sorts (Sequence[tuple[str, str]] | None): Sort fields and directions. Defaults to None.
            filters (FilterGroup | None): Applied filter conditions. Defaults to None.

        Returns:
            Sequence[Any]: List of role data objects.
        """
        roles = await self.dao.get_all_roles(limit=limit)
        return [self._to_admin_object(role) for role in roles]

    async def count(
        self,
        request: Request,
        q: str | None = None,
        filters: FilterGroup | None = None,
    ) -> int:
        """
        Count total number of role records in database.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            q (str | None): Optional search query string. Defaults to None.
            filters (FilterGroup | None): Applied filter conditions. Defaults to None.

        Returns:
            int: Total count of role records.
        """
        record = await self.db.fetch("SELECT COUNT(*) as cnt FROM roles", fetch_row=True)
        return int(record["cnt"]) if record else 0

    async def find_by_pk(self, request: Request, pk: UUID | str) -> Any | None:
        """
        Find a single role by primary key.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (UUID | str): Primary key (UUID or UUID string) of the role.

        Returns:
            Any | None: Role data object if found, None otherwise.
        """
        role_id = UUID(str(pk))
        role = await self.dao.get_role_by_id(role_id)
        if not role:
            return None
        return self._to_admin_object(role)

    async def find_by_pks(self, request: Request, pks: list[Any]) -> Sequence[Any]:
        """
        Find multiple roles by primary keys in a single bulk SQL query.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of role primary keys (UUIDs or strings).

        Returns:
            Sequence[Any]: List of matching role data objects.
        """
        if not pks:
            return []
        uuid_pks = [UUID(str(pk)) for pk in pks]
        roles = await self.dao.get_by_ids(uuid_pks)
        return [self._to_admin_object(role) for role in roles]

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        """
        Create a new role with associated permissions.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            data (dict[str, Any]): Dictionary of field values submitted from form.

        Returns:
            Any: Created role data object.
        """
        permission_names = data.get("permissions") or []
        all_perms = await self.dao.get_all_permissions()
        perm_map = {p.name: p.id for p in all_perms}
        permission_ids = [perm_map[name] for name in permission_names if name in perm_map]

        role_create = RoleCreate(
            name=data["name"],
            description=data.get("description"),
            permission_ids=permission_ids,
        )
        role = await self.dao.create_role(role_create)
        return self._to_admin_object(role)

    async def edit(self, request: Request, pk: UUID | str, data: dict[str, Any]) -> Any:
        """
        Update an existing role's name, description, and permissions.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (UUID | str): Primary key (UUID or string) of the role to update.
            data (dict[str, Any]): Updated field values submitted from form.

        Returns:
            Any: Updated role data object.

        Raises:
            ValueError: If role with given PK does not exist.
        """
        role_id = UUID(str(pk))
        permission_names = data.get("permissions")
        permission_ids = None
        if permission_names is not None:
            all_perms = await self.dao.get_all_permissions()
            perm_map = {p.name: p.id for p in all_perms}
            permission_ids = [perm_map[name] for name in permission_names if name in perm_map]

        role_update = RoleUpdate(
            name=data.get("name"),
            description=data.get("description"),
            permission_ids=permission_ids,
        )
        role = await self.dao.update_role(role_id, role_update)
        if not role:
            raise ValueError(f"Role with ID {pk} not found")

        return self._to_admin_object(role)

    async def delete(self, request: Request, pks: list[Any]) -> int:
        """
        Delete roles by primary keys.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of primary keys of roles to delete.

        Returns:
            int: Number of deleted role records.
        """
        count_deleted = 0
        for pk in pks:
            role_id = UUID(str(pk))
            await self.dao.delete_role(role_id)
            count_deleted += 1
        return count_deleted
