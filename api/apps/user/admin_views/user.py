"""
Admin views for the User domain (Users management).
"""

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette_admin import row_action
from starlette_admin.fields import BooleanField, DateTimeField, EmailField, StringField, TagsField, UUIDField
from starlette_admin.filters import FilterGroup

from api.apps.user.v0.dao.user import UserDAO
from api.apps.user.v0.schemas.user import UserData, UserUpdate
from api.core.database import DataBase
from api.utils.admin_view import BaseAppAdminView


class UserAdminView(BaseAppAdminView):
    """
    Custom Starlette-Admin view for managing Users via raw SQL and UserDAO.
    """

    key = "user"
    identity = "user"
    name = "User"
    label = "Users"
    menu_label = "Users"
    icon = "fa-solid fa-users"
    pk_attr = "id"

    fields = [
        UUIDField("id", label="ID", read_only=True),
        EmailField("email", label="Email", required=True),
        StringField("username", label="Username", required=True),
        StringField("full_name", label="Full Name"),
        BooleanField("is_active", label="Is Active"),
        BooleanField("is_superuser", label="Is Superuser"),
        TagsField("roles", label="Roles"),
        DateTimeField("created_at", label="Created At", read_only=True),
        DateTimeField("updated_at", label="Updated At", read_only=True),
    ]

    def __init__(self, db: DataBase) -> None:
        """
        Initialize UserAdminView with DataBase and UserDAO.

        Args:
            db (DataBase): Database connection instance.
        """
        super().__init__()
        self.db = db
        self.dao = UserDAO(self.db)

    @staticmethod
    def _to_admin_object(user: UserData) -> SimpleNamespace:
        """
        Convert a UserData Pydantic model into a Starlette-Admin compatible object.

        Args:
            user (UserData): UserData Pydantic model instance.

        Returns:
            SimpleNamespace: Admin-compatible object with dynamically mapped fields.
        """
        data = user.model_dump()
        if "roles" in data and isinstance(data["roles"], list):
            data["roles"] = [r.get("name") if isinstance(r, dict) else r for r in data["roles"]]
        return SimpleNamespace(**data)

    async def get_pk_value(self, request: Request, obj: Any) -> Any:
        """
        Extract the primary key value from a user object or dictionary.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            obj (Any): The user data object or dictionary.

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
        Retrieve paginated list of users with associated roles.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            skip (int): Number of records to skip for pagination. Defaults to 0.
            limit (int): Maximum number of records to return. Defaults to 100.
            q (str | None): Optional search query string. Defaults to None.
            sorts (Sequence[tuple[str, str]] | None): Sort fields and directions. Defaults to None.
            filters (FilterGroup | None): Applied filter conditions. Defaults to None.

        Returns:
            Sequence[Any]: List of user data objects with formatted role tags.
        """
        users = await self.dao.get_all_paginated(limit=limit, skip=skip)
        return [self._to_admin_object(u) for u in users]

    async def count(
        self,
        request: Request,
        q: str | None = None,
        filters: FilterGroup | None = None,
    ) -> int:
        """
        Count total number of user records in database.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            q (str | None): Optional search query string. Defaults to None.
            filters (FilterGroup | None): Applied filter conditions. Defaults to None.

        Returns:
            int: Total count of user records.
        """
        record = await self.db.fetch("SELECT COUNT(*) as cnt FROM users", fetch_row=True)
        return int(record["cnt"]) if record else 0

    async def find_by_pk(self, request: Request, pk: UUID | str) -> Any | None:
        """
        Find a single user by primary key.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (UUID | str): Primary key (UUID or string) of the user.

        Returns:
            Any | None: User data object if found, None otherwise.
        """
        user_id = UUID(str(pk))
        user = await self.dao.get_by_id(user_id)
        if not user:
            return None
        return self._to_admin_object(user)

    async def find_by_pks(self, request: Request, pks: list[Any]) -> Sequence[Any]:
        """
        Find multiple users by primary keys in a single bulk query.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of user primary keys (UUIDs or strings).

        Returns:
            Sequence[Any]: List of matching user data objects.
        """
        if not pks:
            return []
        uuid_pks = [UUID(str(pk)) for pk in pks]
        users = await self.dao.get_by_ids(uuid_pks)
        return [self._to_admin_object(u) for u in users]

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        """
        Placeholder create method required by BaseModelView abstract interface.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            data (dict[str, Any]): Dictionary of submitted form field values.

        Raises:
            NotImplementedError: Direct creation via admin portal is disabled.
        """
        raise NotImplementedError("Direct user creation in admin portal is disabled.")

    async def edit(self, request: Request, pk: UUID | str, data: dict[str, Any]) -> Any:
        """
        Update an existing user's details (full name, active status, superuser status).

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (UUID | str): Primary key (UUID or string) of user to update.
            data (dict[str, Any]): Updated field values submitted from form.

        Returns:
            Any: Updated user data object.

        Raises:
            ValueError: If user with given PK does not exist.
        """
        user_id = UUID(str(pk))
        user_update = UserUpdate(
            full_name=data.get("full_name"),
            is_active=data.get("is_active"),
            is_superuser=data.get("is_superuser"),
        )
        user = await self.dao.update_user(user_id, user_update)
        if not user:
            raise ValueError(f"User with ID {pk} not found")
        return self._to_admin_object(user)

    async def delete(self, request: Request, pks: list[Any]) -> int:
        """
        Delete users by primary keys.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of primary keys of users to delete.

        Returns:
            int: Number of deleted user records.
        """
        count_deleted = 0
        for pk in pks:
            user_id = UUID(str(pk))
            query = "DELETE FROM users WHERE id = $1 RETURNING id;"
            row = await self.db.fetch(query, user_id, fetch_row=True)
            if row:
                count_deleted += 1
        return count_deleted

    @row_action(
        name="toggle_active",
        text="Toggle Active Status",
        icon_class="fa-solid fa-user-slash",
    )
    async def toggle_active_action(self, _request: Request, pk: Any) -> str:
        """
        Row action to toggle a user's active status between active and inactive.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (Any): Primary key of target user.

        Returns:
            str: Success notification message for flash display.

        Raises:
            ValueError: If target user does not exist.
        """
        user_id = UUID(str(pk))
        user = await self.dao.get_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        new_status = not user.is_active
        await self.dao.update_user(user_id, UserUpdate(is_active=new_status))
        status_text = "activated" if new_status else "deactivated"
        return f"User '{user.email}' has been successfully {status_text}."
