from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette_admin.exceptions import ActionFailed
from starlette_admin.fields import DateTimeField, IntegerField, JSONField, StringField, TextAreaField, UUIDField
from starlette_admin.filters import FilterGroup, FilterRule

from api.core.database import CustomRecord, DataBase
from api.utils.admin_filters import extract_date_range
from api.utils.admin_view import BaseAppAdminView


class WebhookLogAdminView(BaseAppAdminView):
    """
    Custom Starlette-Admin view for inspecting TimescaleDB webhook logs (INBOUND and OUTBOUND).
    Read-only view with advanced date range and status/direction filtering.
    """

    key = "webhook_log"
    identity = "webhook_log"
    name = "Webhook Log"
    label = "Webhook Logs"
    menu_label = "Webhook Logs"
    icon = "fa-solid fa-network-wired"
    pk_attr = "id"

    fields = [
        UUIDField("id", label="ID", read_only=True, exclude_from_list=True),
        StringField("direction", label="Direction", read_only=True),
        StringField("status", label="Status", read_only=True),
        IntegerField("status_code", label="Status Code", read_only=True),
        StringField("source", label="Source", read_only=True),
        StringField("event_name", label="Event", read_only=True),
        StringField("url", label="URL / Path", read_only=True),
        IntegerField("execution_time_ms", label="Duration (ms)", read_only=True),
        StringField("ip_address", label="IP Address", read_only=True),
        DateTimeField("created_at", label="Logged At", read_only=True),
        JSONField("payload", label="Payload", read_only=True, exclude_from_list=True),
        JSONField("request_headers", label="Request Headers", read_only=True, exclude_from_list=True),
        JSONField("response_headers", label="Response Headers", read_only=True, exclude_from_list=True),
        TextAreaField("response_body", label="Response Body", read_only=True, exclude_from_list=True),
        TextAreaField("error_message", label="Error Message", read_only=True, exclude_from_list=True),
    ]

    def __init__(self, db: DataBase) -> None:
        super().__init__()
        self.db = db

    def can_create(self, request: Request) -> bool:
        return False

    def can_edit(self, request: Request) -> bool:
        return False

    def can_delete(self, request: Request) -> bool:
        return False

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        raise ActionFailed("Webhook logs are immutable and cannot be created via admin UI.")

    async def edit(self, request: Request, pk: UUID | str, data: dict[str, Any]) -> Any:
        raise ActionFailed("Webhook logs are immutable and cannot be edited via admin UI.")

    async def delete(self, request: Request, pks: list[Any]) -> int:
        raise ActionFailed("Webhook logs are immutable and cannot be deleted via admin UI.")

    @staticmethod
    def _to_admin_object(record: dict[str, Any] | CustomRecord) -> SimpleNamespace:
        data = dict(record)
        return SimpleNamespace(**data)

    @staticmethod
    def _extract_date_bounds(filters: FilterGroup | None) -> tuple[datetime, datetime]:
        now = datetime.now(timezone.utc)
        from_date: datetime | None = None
        to_date: datetime | None = None

        if filters and hasattr(filters, "rules"):
            for rule in filters.rules:
                if isinstance(rule, FilterRule) and rule.field == "created_at":
                    start, end = extract_date_range(rule)
                    from_date = start or from_date
                    to_date = end or to_date

        to_date = to_date or now
        from_date = from_date or (to_date - timedelta(days=30))
        return from_date, to_date

    def _build_filter_query(
        self,
        filters: FilterGroup | None,
        limit: int,
        skip: int,
        q: str | None = None,
    ) -> tuple[str, list[Any]]:
        conditions = ["1=1"]
        params: list[Any] = []

        if filters and hasattr(filters, "rules"):
            for rule in filters.rules:
                if (
                    isinstance(rule, FilterRule)
                    and rule.field in ("direction", "status", "source", "event_name")
                    and rule.value
                ):
                    params.append(rule.value)
                    conditions.append(f"{rule.field} = ${len(params)}")

        from_date, to_date = self._extract_date_bounds(filters)
        params.extend([from_date, to_date])
        conditions.append(f"created_at >= ${len(params) - 1} AND created_at <= ${len(params)}")

        if q and q.strip():
            search = f"%{q.strip()}%"
            params.append(search)
            idx = len(params)
            conditions.append(
                f"(event_name ILIKE ${idx} OR source ILIKE ${idx} OR url ILIKE ${idx} OR error_message ILIKE ${idx})"
            )

        params.extend([limit, skip])
        where_clause = " AND ".join(conditions)

        query_parts = [
            "SELECT * FROM webhook_logs WHERE",
            where_clause,
            "ORDER BY created_at DESC LIMIT",
            f"${len(params) - 1}",
            "OFFSET",
            f"${len(params)};",
        ]
        return " ".join(query_parts), params

    async def find_all(
        self,
        request: Request,
        skip: int = 0,
        limit: int = 100,
        q: str | None = None,
        sorts: Sequence[tuple[str, str]] | None = None,
        filters: FilterGroup | None = None,
    ) -> Sequence[Any]:
        query, params = self._build_filter_query(filters, limit, skip, q=q)
        records = await self.db.fetch(query, *params, fetch_row=False)
        return [self._to_admin_object(r) for r in records]

    async def count(
        self,
        request: Request,
        q: str | None = None,
        filters: FilterGroup | None = None,
    ) -> int:
        val = await self.db.fetchval("SELECT approximate_row_count('webhook_logs')")
        return int(val) if val is not None else 0

    async def find_by_pk(self, request: Request, pk: Any) -> Any | None:
        query = "SELECT * FROM webhook_logs WHERE id = $1 ORDER BY created_at DESC LIMIT 1"
        record = await self.db.fetch(query, UUID(str(pk)), fetch_row=True)
        return self._to_admin_object(record) if record else None

    async def find_by_pks(self, request: Request, pks: list[Any]) -> Sequence[Any]:
        if not pks:
            return []
        log_ids = [UUID(str(pk)) for pk in pks]
        query = "SELECT * FROM webhook_logs WHERE id = ANY($1::uuid[]) ORDER BY created_at DESC"
        records = await self.db.fetch(query, log_ids, fetch_row=False)
        return [self._to_admin_object(r) for r in records]
