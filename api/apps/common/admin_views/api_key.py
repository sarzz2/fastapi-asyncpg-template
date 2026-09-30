from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette_admin import flash, row_action
from starlette_admin.exceptions import ActionFailed
from starlette_admin.fields import BooleanField, DateTimeField, IntegerField, StringField, TagsField, UUIDField
from starlette_admin.filters import FilterGroup

from api.apps.common.utils import generate_api_key
from api.apps.common.v0.dao.api_key import ApiKeyDAO
from api.apps.common.v0.schemas.api_key import ApiKeyCreateInternal, ApiKeyUpdate
from api.core.database import CustomRecord, DataBase
from api.core.redis import redis_client
from api.shared.redis_keys import RedisKeys
from api.utils.admin_view import BaseAppAdminView


class ApiKeyAdminView(BaseAppAdminView):
    """
    Starlette-Admin view for managing and inspecting API Keys.
    """

    key = "api_key"
    identity = "api_key"
    name = "API Key"
    label = "API Keys"
    menu_label = "API Keys"
    icon = "fa-solid fa-key"

    fields = [
        StringField("name", label="Key Name", required=True),
        StringField("prefix", label="Prefix", read_only=True),
        UUIDField("id", label="ID", read_only=True),
        StringField("created_by_name", label="Created By", read_only=True),
        UUIDField("created_by", label="Created By ID", read_only=True, exclude_from_list=True),
        TagsField("scopes", label="Scopes", help_text="Granted scopes e.g. users:read"),
        IntegerField("rate_limit", label="Rate Limit (req/min)"),
        BooleanField("is_active", label="Active"),
        DateTimeField("expires_at", label="Expires At"),
        DateTimeField("last_used_at", label="Last Used At", read_only=True),
        DateTimeField("created_at", label="Created At", read_only=True),
        DateTimeField("updated_at", label="Updated At", read_only=True),
    ]

    def __init__(self, db: DataBase) -> None:
        super().__init__()
        self.db = db
        self.dao = ApiKeyDAO(self.db)

    @staticmethod
    def _to_admin_object(record: dict[str, Any] | CustomRecord) -> SimpleNamespace:
        data = dict(record)
        if "scopes" in data and not isinstance(data["scopes"], list):
            data["scopes"] = list(data["scopes"]) if data["scopes"] else []
        return SimpleNamespace(**data)

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        """
        Create a new API key via admin UI. Generates a secure raw key, hashes it,
        stores the record, and displays the raw key via a flash notification.

        Args:
            request (Request): Starlette request.
            data (dict[str, Any]): Creation data from admin form.

        Returns:
            Any: Admin object of the created record.
        """
        raw_key, prefix, hashed_key = generate_api_key()
        created_by = self.get_current_admin_user_id(request)

        raw_scopes = data.get("scopes") or []
        if isinstance(raw_scopes, str):
            scopes = [s.strip() for s in raw_scopes.split(",") if s.strip()]
        else:
            scopes = list(raw_scopes)

        is_active = data.get("is_active")
        internal_key = ApiKeyCreateInternal(
            name=data["name"],
            prefix=prefix,
            hashed_key=hashed_key,
            scopes=scopes,
            rate_limit=data.get("rate_limit"),
            expires_at=data.get("expires_at"),
            created_by=created_by,
            is_active=is_active if is_active is not None else True,
        )
        created_key = await self.dao.create_api_key(internal_key)

        flash(
            request,
            f"API Key '{created_key.name}' created successfully! "
            f"Raw secret key: {raw_key} (Store this securely! It will not be shown again).",
            "success",
        )
        return await self.find_by_pk(request, created_key.id)

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
        Retrieve paginated list of API keys for admin display.

        Args:
            request (Request): Starlette request.
            skip (int): Records to offset.
            limit (int): Maximum records to retrieve.
            q (str | None): Optional search query.
            sorts (Sequence[tuple[str, str]] | None): Sorting pairs.
            filters (FilterGroup | None): Applied filter group.

        Returns:
            Sequence[Any]: List of admin key objects.
        """
        if q and q.strip():
            search = f"%{q.strip()}%"
            query = (
                "SELECT k.*, COALESCE(NULLIF(u.full_name, ''), u.username, 'System') AS created_by_name "
                "FROM api_keys k LEFT JOIN users u ON k.created_by = u.id "
                "WHERE (k.name ILIKE $1 OR k.prefix ILIKE $1 OR u.email ILIKE $1) "
                "ORDER BY k.created_at DESC LIMIT $2 OFFSET $3;"
            )
            records = await self.db.fetch(query, search, limit, skip, fetch_row=False)
        else:
            query = (
                "SELECT k.*, COALESCE(NULLIF(u.full_name, ''), u.username, 'System') AS created_by_name "
                "FROM api_keys k LEFT JOIN users u ON k.created_by = u.id "
                "ORDER BY k.created_at DESC LIMIT $1 OFFSET $2;"
            )
            records = await self.db.fetch(query, limit, skip, fetch_row=False)
        return [self._to_admin_object(r) for r in records]

    async def count(
        self,
        request: Request,
        q: str | None = None,
        filters: FilterGroup | None = None,
    ) -> int:
        """
        Count total API keys matching search query for admin pagination.

        Args:
            request (Request): Starlette request.
            q (str | None): Optional search query.
            filters (FilterGroup | None): Applied filter group.

        Returns:
            int: Total record count.
        """
        if q and q.strip():
            search = f"%{q.strip()}%"
            query = (
                "SELECT COUNT(*) FROM api_keys k LEFT JOIN users u ON k.created_by = u.id "
                "WHERE (k.name ILIKE $1 OR k.prefix ILIKE $1 OR u.email ILIKE $1);"
            )
            val = await self.db.fetchval(query, search)
        else:
            query = "SELECT COUNT(*) FROM api_keys;"
            val = await self.db.fetchval(query)
        return int(val) if val else 0

    async def find_by_pk(self, request: Request, pk: Any) -> Any | None:
        """
        Find single API key record by primary key UUID.

        Args:
            request (Request): Starlette request.
            pk (Any): Primary key value.

        Returns:
            Any | None: Admin object if found, None otherwise.
        """
        query = """
            SELECT
                k.*,
                COALESCE(NULLIF(u.full_name, ''), u.username, 'System') AS created_by_name
            FROM api_keys k
            LEFT JOIN users u ON k.created_by = u.id
            WHERE k.id = $1
        """
        record = await self.db.fetch(query, UUID(str(pk)), fetch_row=True)
        return self._to_admin_object(record) if record else None

    async def find_by_pks(self, request: Request, pks: list[Any]) -> Sequence[Any]:
        """
        Find multiple API key records by list of primary keys.

        Args:
            request (Request): Starlette request.
            pks (list[Any]): Primary key values.

        Returns:
            Sequence[Any]: List of admin objects.
        """
        if not pks:
            return []
        key_ids = [UUID(str(pk)) for pk in pks]
        query = """
            SELECT
                k.*,
                COALESCE(NULLIF(u.full_name, ''), u.username, 'System') AS created_by_name
            FROM api_keys k
            LEFT JOIN users u ON k.created_by = u.id
            WHERE k.id = ANY($1::uuid[])
            ORDER BY k.created_at DESC
        """
        records = await self.db.fetch(query, key_ids, fetch_row=False)
        return [self._to_admin_object(r) for r in records]

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        """
        Edit an existing API key from admin UI.

        Args:
            request (Request): Starlette request.
            pk (Any): Key primary key.
            data (dict[str, Any]): Updated fields.

        Returns:
            Any: Updated admin object.
        """
        key_id = UUID(str(pk))
        existing = await self.dao.get_api_key_by_id(key_id)

        raw_scopes = data.get("scopes")
        if raw_scopes is not None:
            if isinstance(raw_scopes, str):
                scopes = [s.strip() for s in raw_scopes.split(",") if s.strip()]
            else:
                scopes = list(raw_scopes)
        else:
            scopes = None

        update_data = ApiKeyUpdate(
            name=data.get("name"),
            scopes=scopes,
            rate_limit=data.get("rate_limit"),
            expires_at=data.get("expires_at"),
            is_active=data.get("is_active"),
        )
        await self.dao.update_api_key(key_id, update_data)

        if existing and existing.hashed_key:
            await redis_client.client.delete(RedisKeys.API_KEY_CACHE.format(hashed_key=existing.hashed_key))

        return await self.find_by_pk(request, pk)

    async def delete(self, request: Request, pks: list[Any]) -> int:
        """
        Delete multiple API keys by primary key.

        Args:
            request (Request): Starlette request.
            pks (list[Any]): Primary key values.

        Returns:
            int: Number of deleted records.
        """
        deleted_count = 0
        for pk in pks:
            key_id = UUID(str(pk))
            existing = await self.dao.get_api_key_by_id(key_id)
            if await self.dao.delete_api_key(key_id):
                deleted_count += 1
                if existing and existing.hashed_key:
                    await redis_client.client.delete(RedisKeys.API_KEY_CACHE.format(hashed_key=existing.hashed_key))
        return deleted_count

    @row_action(
        name="rotate_key",
        text="Rotate Secret",
        icon_class="fa-solid fa-arrows-rotate",
        confirmation="Are you sure you want to rotate this API key? Existing clients will immediately lose access.",
    )
    async def rotate_action(self, request: Request, pk: Any) -> str:
        """
        Row action to rotate the secret of an API key.

        Args:
            request (Request): Starlette request.
            pk (Any): Primary key value.

        Returns:
            str: Notification flash message.
        """
        key_id = UUID(str(pk))
        existing = await self.dao.get_api_key_by_id(key_id)
        if not existing:
            raise ActionFailed("API Key not found.")

        raw_key, prefix, new_hashed_key = generate_api_key()
        await self.dao.rotate_api_key(key_id, new_prefix=prefix, new_hashed_key=new_hashed_key)

        if existing.hashed_key:
            await redis_client.client.delete(RedisKeys.API_KEY_CACHE.format(hashed_key=existing.hashed_key))

        flash(
            request,
            f"API Key '{existing.name}' rotated successfully! "
            f"New secret key: {raw_key} (Store this securely! It will not be shown again).",
            "warning",
        )
        return f"API Key rotated. New raw key: {raw_key}"

    @row_action(
        name="deactivate_key",
        text="Deactivate",
        icon_class="fa-solid fa-ban",
    )
    async def deactivate_action(self, request: Request, pk: Any) -> str:
        """
        Row action to deactivate an active API key.

        Args:
            request (Request): Starlette request.
            pk (Any): Primary key value.

        Returns:
            str: Notification flash message.
        """
        key_id = UUID(str(pk))
        existing = await self.dao.get_api_key_by_id(key_id)
        await self.dao.update_api_key(key_id, ApiKeyUpdate(is_active=False))
        if existing and existing.hashed_key:
            await redis_client.client.delete(RedisKeys.API_KEY_CACHE.format(hashed_key=existing.hashed_key))
        message = f"API Key '{existing.name if existing else pk}' successfully deactivated."
        flash(request, message, "info")
        return message

    @row_action(
        name="activate_key",
        text="Activate",
        icon_class="fa-solid fa-check",
    )
    async def activate_action(self, request: Request, pk: Any) -> str:
        """
        Row action to activate an inactive API key.

        Args:
            request (Request): Starlette request.
            pk (Any): Primary key value.

        Returns:
            str: Notification flash message.
        """
        key_id = UUID(str(pk))
        existing = await self.dao.get_api_key_by_id(key_id)
        await self.dao.update_api_key(key_id, ApiKeyUpdate(is_active=True))
        if existing and existing.hashed_key:
            await redis_client.client.delete(RedisKeys.API_KEY_CACHE.format(hashed_key=existing.hashed_key))
        message = f"API Key '{existing.name if existing else pk}' successfully activated."
        flash(request, message, "success")
        return message
