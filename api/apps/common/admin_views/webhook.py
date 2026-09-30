import json
import secrets
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette_admin import flash
from starlette_admin.fields import (
    BooleanField,
    DateTimeField,
    EnumField,
    StringField,
    TextAreaField,
    URLField,
    UUIDField,
)
from starlette_admin.filters import FilterGroup

from api.apps.common.constants import WebhookEvents
from api.apps.common.utils import parse_headers
from api.apps.common.v0.dao.webhook import WebhookDAO
from api.apps.common.v0.schemas.webhook import WebhookEndpointCreateInternal, WebhookEndpointUpdate
from api.core.database import CustomRecord, DataBase
from api.utils.admin_view import BaseAppAdminView


class WebhookEndpointAdminView(BaseAppAdminView):
    """
    Starlette-Admin view for inspecting and managing outbound Webhook Endpoints.
    """

    key = "webhook_endpoint"
    identity = "webhook_endpoint"
    name = "Webhook Endpoint"
    label = "Webhook Endpoints"
    menu_label = "Webhook Endpoints"
    icon = "fa-solid fa-satellite-dish"
    pk_attr = "id"

    fields = [
        UUIDField("id", label="ID", read_only=True),
        UUIDField("created_by", label="Created By ID", read_only=True, exclude_from_list=True),
        StringField("created_by_name", label="Created By", read_only=True),
        URLField("url", label="Endpoint URL", required=True),
        StringField(
            "secret",
            label="Signing Secret",
            help_text="HMAC-SHA256 signature secret (auto-generated if left empty)",
        ),
        TextAreaField("description", label="Description"),
        EnumField(
            "event_types",
            label="Subscribed Events",
            enum=WebhookEvents,
            multiple=True,
            select2=True,
            help_text="Select events to subscribe to",
            required=True,
        ),
        TextAreaField(
            "headers",
            label="Custom Headers",
            help_text="Custom HTTP headers (JSON format or Key: Value per line)",
            exclude_from_list=True,
        ),
        BooleanField("is_active", label="Active"),
        DateTimeField("created_at", label="Created At", read_only=True),
        DateTimeField("updated_at", label="Updated At", read_only=True),
    ]

    def __init__(self, db: DataBase) -> None:
        super().__init__()
        self.db = db
        self.dao = WebhookDAO(self.db)

    @staticmethod
    def _to_admin_object(record: dict[str, Any] | CustomRecord) -> SimpleNamespace:
        data = dict(record)
        if "event_types" in data and not isinstance(data["event_types"], list):
            data["event_types"] = list(data["event_types"]) if data["event_types"] else []
        if "headers" in data:
            if isinstance(data["headers"], (dict, list)) and data["headers"]:
                data["headers"] = json.dumps(data["headers"], indent=2)
            elif not data["headers"]:
                data["headers"] = ""
        return SimpleNamespace(**data)

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        """
        Create a new webhook endpoint via admin UI.

        Args:
            request (Request): Starlette request.
            data (dict[str, Any]): Form data.

        Returns:
            Any: Created admin object.
        """
        secret = data.get("secret")
        if not secret or not str(secret).strip():
            secret = f"whsec_{secrets.token_urlsafe(24)}"

        raw_event_types = data.get("event_types") or []
        if isinstance(raw_event_types, str):
            event_types = [raw_event_types]
        else:
            event_types = list(raw_event_types)

        created_by = self.get_current_admin_user_id(request)
        headers = parse_headers(data.get("headers"))

        endpoint_in = WebhookEndpointCreateInternal(
            url=data["url"],
            description=data.get("description"),
            event_types=event_types,
            headers=headers,
            secret=secret,
            created_by=created_by,
        )
        res = await self.dao.create_endpoint(endpoint_in)
        flash(
            request,
            f"Webhook endpoint created successfully! Signing secret: {secret} (Store this safely).",
            "success",
        )
        return await self.find_by_pk(request, res.id)

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
        Retrieve paginated list of webhook endpoints.

        Args:
            request (Request): Starlette request.
            skip (int): Offset records.
            limit (int): Maximum records.
            q (str | None): Optional search query.
            sorts (Sequence[tuple[str, str]] | None): Sorting pairs.
            filters (FilterGroup | None): Applied filter group.

        Returns:
            Sequence[Any]: List of admin endpoint objects.
        """
        sql = (
            "SELECT w.*, COALESCE(NULLIF(u.full_name, ''), u.username, 'System') AS created_by_name "
            "FROM webhook_endpoints w LEFT JOIN users u ON w.created_by = u.id "
        )
        if q and q.strip():
            sql += "WHERE (w.url ILIKE $1 OR w.description ILIKE $1) ORDER BY w.created_at DESC LIMIT $2 OFFSET $3;"
            records = await self.db.fetch(sql, f"%{q.strip()}%", limit, skip, fetch_row=False)
        else:
            sql += "ORDER BY w.created_at DESC LIMIT $1 OFFSET $2;"
            records = await self.db.fetch(sql, limit, skip, fetch_row=False)
        return [self._to_admin_object(item) for item in records]

    async def count(
        self,
        request: Request,
        q: str | None = None,
        filters: FilterGroup | None = None,
    ) -> int:
        if not (q and q.strip()):
            return int(await self.db.fetchval("SELECT COUNT(*) FROM webhook_endpoints;") or 0)
        search_pattern = f"%{q.strip()}%"
        sql = "SELECT COUNT(*) FROM webhook_endpoints w WHERE (w.url ILIKE $1 OR w.description ILIKE $1);"
        return int(await self.db.fetchval(sql, search_pattern) or 0)

    async def find_by_pk(self, request: Request, pk: Any) -> Any | None:
        """
        Find single webhook endpoint by primary key UUID.

        Args:
            request (Request): Starlette request.
            pk (Any): Primary key value.

        Returns:
            Any | None: Admin object if found, None otherwise.
        """
        query = """
            SELECT
                w.*,
                COALESCE(NULLIF(u.full_name, ''), u.username, 'System') AS created_by_name
            FROM webhook_endpoints w
            LEFT JOIN users u ON w.created_by = u.id
            WHERE w.id = $1
        """
        record = await self.db.fetch(query, UUID(str(pk)), fetch_row=True)
        return self._to_admin_object(record) if record else None

    async def find_by_pks(self, request: Request, pks: list[Any]) -> Sequence[Any]:
        """
        Find multiple webhook endpoints by primary keys.

        Args:
            request (Request): Starlette request.
            pks (list[Any]): Primary key values.

        Returns:
            Sequence[Any]: List of admin objects.
        """
        if not pks:
            return []
        endpoint_ids = [UUID(str(pk)) for pk in pks]
        query = """
            SELECT
                w.*,
                COALESCE(NULLIF(u.full_name, ''), u.username, 'System') AS created_by_name
            FROM webhook_endpoints w
            LEFT JOIN users u ON w.created_by = u.id
            WHERE w.id = ANY($1::uuid[])
            ORDER BY w.created_at DESC
        """
        records = await self.db.fetch(query, endpoint_ids, fetch_row=False)
        return [self._to_admin_object(r) for r in records]

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        """
        Update an existing webhook endpoint from admin UI.

        Args:
            request (Request): Starlette request.
            pk (Any): Endpoint primary key.
            data (dict[str, Any]): Updated fields.

        Returns:
            Any: Updated admin object.
        """
        endpoint_id = UUID(str(pk))
        secret = data.get("secret")
        if secret is not None and not str(secret).strip():
            secret = None

        raw_event_types = data.get("event_types")
        if raw_event_types is not None:
            if isinstance(raw_event_types, str):
                event_types = [raw_event_types]
            else:
                event_types = list(raw_event_types)
        else:
            event_types = None

        headers = parse_headers(data["headers"]) if "headers" in data else None

        update_data = WebhookEndpointUpdate(
            url=data.get("url"),
            description=data.get("description"),
            event_types=event_types,
            headers=headers,
            secret=secret,
            is_active=data.get("is_active"),
        )
        await self.dao.update_endpoint(endpoint_id, update_data)
        flash(request, "Webhook endpoint updated successfully.", "success")
        return await self.find_by_pk(request, pk)

    async def delete(self, request: Request, pks: list[Any]) -> int:
        """
        Delete multiple webhook endpoints by primary key.

        Args:
            request (Request): Starlette request.
            pks (list[Any]): Primary key values.

        Returns:
            int: Number of deleted records.
        """
        deleted_count = 0
        for pk in pks:
            endpoint_id = UUID(str(pk))
            if await self.dao.delete_endpoint(endpoint_id):
                deleted_count += 1
        return deleted_count
