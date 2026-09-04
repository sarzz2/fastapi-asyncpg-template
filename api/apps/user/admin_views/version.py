"""
Admin views for App Version configuration.
"""

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette_admin.fields import (
    BooleanField,
    DateTimeField,
    IntegerField,
    StringField,
    TextAreaField,
    URLField,
    UUIDField,
)
from starlette_admin.filters import FilterGroup

from api.apps.user.v0.dao.version import VersionDAO
from api.apps.user.v0.schemas.version import AppVersionData, AppVersionUpdate
from api.core.database import DataBase
from api.utils.admin_view import BaseAppAdminView


class AppVersionAdminView(BaseAppAdminView):
    """
    Custom Starlette-Admin view for managing App Versions via VersionDAO.
    """

    key = "app_version"
    identity = "app_version"
    name = "App Version"
    label = "App Versions"
    menu_label = "App Versions"
    icon = "fa-solid fa-mobile-screen-button"
    pk_attr = "id"

    fields = [
        UUIDField("id", label="ID", read_only=True),
        StringField("platform", label="Platform", required=True),
        IntegerField("min_build", label="Min Build", required=True),
        IntegerField("latest_build", label="Latest Build", required=True),
        BooleanField("force_update", label="Force Update"),
        TextAreaField("update_message", label="Update Message"),
        URLField("update_url", label="Update URL"),
        DateTimeField("created_at", label="Created At", read_only=True),
        DateTimeField("updated_at", label="Updated At", read_only=True),
    ]

    def __init__(self, db: DataBase) -> None:
        """
        Initialize AppVersionAdminView with VersionDAO.

        Args:
            db (DataBase): Database connection instance.
        """
        super().__init__()
        self.db = db
        self.dao = VersionDAO(self.db)

    @staticmethod
    def _to_admin_object(version: AppVersionData) -> SimpleNamespace:
        """
        Convert AppVersionData Pydantic model into a Starlette-Admin compatible object.

        Args:
            version (AppVersionData): AppVersionData Pydantic model instance.

        Returns:
            SimpleNamespace: Admin-compatible object with dynamically mapped fields.
        """
        return SimpleNamespace(**version.model_dump())

    async def get_pk_value(self, request: Request, obj: Any) -> Any:
        """
        Extract primary key (ID) from app version object or dictionary.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            obj (Any): The app version data object or dictionary.

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
        Retrieve paginated list of app version configurations.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            skip (int): Number of records to skip for pagination. Defaults to 0.
            limit (int): Maximum number of records to return. Defaults to 100.
            q (str | None): Optional search query string. Defaults to None.
            sorts (Sequence[tuple[str, str]] | None): Sort fields and directions. Defaults to None.
            filters (FilterGroup | None): Applied filter conditions. Defaults to None.

        Returns:
            Sequence[Any]: List of app version objects.
        """
        query = "SELECT * FROM app_versions ORDER BY platform LIMIT $1 OFFSET $2"
        records = await self.db.fetch(query, limit, skip, fetch_row=False)
        if not records:
            return []
        versions = [AppVersionData.model_validate(dict(r)) for r in records]
        return [self._to_admin_object(v) for v in versions]

    async def count(
        self,
        request: Request,
        q: str | None = None,
        filters: FilterGroup | None = None,
    ) -> int:
        """
        Count total number of app version records in database.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            q (str | None): Optional search query string. Defaults to None.
            filters (FilterGroup | None): Applied filter conditions. Defaults to None.

        Returns:
            int: Total count of app version records.
        """
        record = await self.db.fetch("SELECT COUNT(*) as cnt FROM app_versions", fetch_row=True)
        return int(record["cnt"]) if record else 0

    async def find_by_pk(self, request: Request, pk: UUID | str) -> Any | None:
        """
        Find a single app version by primary key.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (UUID | str): Primary key (UUID or string) of the app version.

        Returns:
            Any | None: App version data object if found, None otherwise.
        """
        version_id = UUID(str(pk))
        query = "SELECT * FROM app_versions WHERE id = $1"
        record = await self.db.fetch(query, version_id, fetch_row=True)
        if not record:
            return None
        version = AppVersionData.model_validate(dict(record))
        return self._to_admin_object(version)

    async def find_by_pks(self, request: Request, pks: list[Any]) -> Sequence[Any]:
        """
        Find multiple app versions by primary keys in a single bulk SQL query.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of primary keys (UUIDs or strings).

        Returns:
            Sequence[Any]: List of matching app version objects.
        """
        if not pks:
            return []
        uuid_pks = [UUID(str(pk)) for pk in pks]
        query = "SELECT * FROM app_versions WHERE id = ANY($1::uuid[])"
        records = await self.db.fetch(query, uuid_pks, fetch_row=False)
        if not records:
            return []
        versions = [AppVersionData.model_validate(dict(r)) for r in records]
        return [self._to_admin_object(v) for v in versions]

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        """
        Create a new platform app version configuration.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            data (dict[str, Any]): Dictionary of field values submitted from form.

        Returns:
            Any: Created app version object.
        """
        query = """
            INSERT INTO app_versions (platform, min_build, latest_build, force_update, update_message, update_url)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
        """
        record = await self.db.write(
            query,
            data["platform"].lower(),
            data["min_build"],
            data["latest_build"],
            data.get("force_update", False),
            data.get("update_message"),
            data.get("update_url"),
        )
        version = AppVersionData.model_validate(dict(record))
        return self._to_admin_object(version)

    async def edit(self, request: Request, pk: UUID | str, data: dict[str, Any]) -> Any:
        """
        Update an existing app version's build numbers and flags via VersionDAO.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pk (UUID | str): Primary key (UUID or string) of app version to update.
            data (dict[str, Any]): Updated field values submitted from form.

        Returns:
            Any: Updated app version object.

        Raises:
            ValueError: If target app version record is not found.
        """
        platform = data.get("platform")
        if not platform:
            version_id = UUID(str(pk))
            existing = await self.db.fetch(
                "SELECT platform FROM app_versions WHERE id = $1", version_id, fetch_row=True
            )
            if not existing:
                raise ValueError(f"App version with ID {pk} not found")
            platform = existing["platform"]

        update_data = AppVersionUpdate(
            min_build=data.get("min_build"),
            latest_build=data.get("latest_build"),
            force_update=data.get("force_update"),
            update_message=data.get("update_message"),
            update_url=data.get("update_url"),
        )
        version = await self.dao.update_version_info(platform, update_data)
        if not version:
            raise ValueError(f"App version for platform {platform} not found")
        return self._to_admin_object(version)

    async def delete(self, request: Request, pks: list[Any]) -> int:
        """
        Delete app version configurations by primary keys.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.
            pks (list[Any]): List of primary keys of records to delete.

        Returns:
            int: Number of deleted app version records.
        """
        count_deleted = 0
        for pk in pks:
            version_id = UUID(str(pk))
            query = "DELETE FROM app_versions WHERE id = $1 RETURNING id;"
            row = await self.db.fetch(query, version_id, fetch_row=True)
            if row:
                count_deleted += 1
        return count_deleted
