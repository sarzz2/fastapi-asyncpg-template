"""
Admin views for Audit Log inspection.
"""

import contextlib
import json
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, NamedTuple
from uuid import UUID

from starlette.requests import Request
from starlette_admin.exceptions import ActionFailed
from starlette_admin.fields import DateTimeField, JSONField, StringField, UUIDField
from starlette_admin.filters import FilterGroup, FilterRule

from api.core.database import CustomRecord, DataBase
from api.utils.admin_filters import extract_date_range
from api.utils.admin_view import BaseAppAdminView


def _build_search_clause(params: list[Any], q: str | None) -> str | None:
    """Build parameterized full-text search condition across relevant fields."""
    if not q or not q.strip():
        return None
    search_str = q.strip()
    params.append(f"%{search_str}%")
    s_idx = len(params)
    search_conds = [
        f"u.full_name ILIKE ${s_idx}",
        f"u.username ILIKE ${s_idx}",
        f"u.email ILIKE ${s_idx}",
        f"a.action ILIKE ${s_idx}",
        f"a.resource ILIKE ${s_idx}",
        f"a.resource_id ILIKE ${s_idx}",
        f"a.ip_address ILIKE ${s_idx}",
    ]
    try:
        uuid_val = UUID(search_str)
        params.append(uuid_val)
        u_idx = len(params)
        search_conds.append(f"a.id = ${u_idx}::uuid")
        search_conds.append(f"a.actor_id = ${u_idx}::uuid")
    except ValueError:
        pass
    return f"({' OR '.join(search_conds)})"


class AuditLogQueryFilters(NamedTuple):
    """Container for extracted audit log query filter values."""

    from_date: datetime
    to_date: datetime
    actor_id: UUID | None
    actor_name: str | None
    resource: str | None
    action: str | None


class AuditLogAdminView(BaseAppAdminView):
    """
    Custom Starlette-Admin view for inspecting immutable audit logs.
    """

    key = "audit_log"
    identity = "audit_log"
    name = "Audit Log"
    label = "Audit Logs"
    menu_label = "Audit Logs"
    icon = "fa-solid fa-clock-rotate-left"
    pk_attr = "id"

    fields = [
        UUIDField("id", label="ID", read_only=True, exclude_from_list=True),
        UUIDField("actor_id", label="Actor ID", read_only=True, exclude_from_list=True),
        StringField("actor_name", label="Actor Name", read_only=True),
        StringField("actor_username", label="Actor Username", read_only=True, exclude_from_list=True),
        StringField("actor_email", label="Actor Email", read_only=True),
        StringField("action", label="Action", read_only=True),
        StringField("resource", label="Resource", read_only=True),
        StringField("resource_id", label="Resource ID", read_only=True),
        JSONField(
            "details",
            label="Details",
            read_only=True,
            exclude_from_list=True,
            viewer_collapsed=False,
            viewer_root_collapsable=True,
        ),
        StringField("ip_address", label="IP Address", read_only=True),
        DateTimeField("created_at", label="Created At", read_only=True),
    ]

    def can_create(self, request: Request) -> bool:
        """Disable creation of audit logs from admin UI."""
        return False

    def can_edit(self, request: Request) -> bool:
        """Disable editing audit logs from admin UI (immutable)."""
        return False

    def can_delete(self, request: Request) -> bool:
        """Disable deletion of audit logs from admin UI."""
        return False

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        """Audit logs are immutable and cannot be created via admin UI."""
        raise ActionFailed("Audit logs cannot be created via admin UI.")

    async def edit(self, request: Request, pk: UUID | str, data: dict[str, Any]) -> Any:
        """Audit logs are immutable and cannot be edited via admin UI."""
        raise ActionFailed("Audit logs cannot be edited via admin UI.")

    async def delete(self, request: Request, pks: list[Any]) -> int:
        """Audit logs are immutable and cannot be deleted via admin UI."""
        raise ActionFailed("Audit logs cannot be deleted via admin UI.")

    def __init__(self, db: DataBase) -> None:
        """
        Initialize AuditLogAdminView with DataBase instance.

        Args:
            db (DataBase): Database connection instance.
        """
        super().__init__()
        self.db = db

    @staticmethod
    def _to_admin_object(record: dict[str, Any] | CustomRecord) -> SimpleNamespace:
        """
        Convert record to Starlette-Admin compatible object.

        Args:
            record: Database record.

        Returns:
            SimpleNamespace: Admin compatible object.
        """
        data = dict(record)
        details = data.get("details")
        if isinstance(details, str):
            with contextlib.suppress(Exception):
                data["details"] = json.loads(details)
        return SimpleNamespace(**data)

    async def get_pk_value(self, request: Request, obj: Any) -> Any:
        """
        Extract primary key (ID) from audit log object or dictionary.

        Args:
            request (Request): The incoming request.
            obj (Any): The audit log object or dictionary.

        Returns:
            Any: The primary key (ID) value.
        """
        if isinstance(obj, dict):
            return obj.get("id")
        return getattr(obj, "id", None)

    @staticmethod
    def _extract_query_filters(
        filters: FilterGroup | None,
    ) -> AuditLogQueryFilters:
        """
        Extract from_date, to_date, actor_id, actor_name, resource, and action directly from FilterGroup.
        Defaults date range to last 30 days if not provided.
        """
        now = datetime.now(timezone.utc)
        from_date: datetime | None = None
        to_date: datetime | None = None
        actor_id: UUID | None = None
        actor_name: str | None = None
        resource: str | None = None
        action: str | None = None

        if filters and hasattr(filters, "rules"):
            for rule in filters.rules:
                if not isinstance(rule, FilterRule):
                    continue
                if rule.field == "created_at":
                    start, end = extract_date_range(rule)
                    from_date = start or from_date
                    to_date = end or to_date
                elif rule.field == "actor_id" and rule.value:
                    actor_id = UUID(str(rule.value))
                elif rule.field == "actor_name" and rule.value:
                    actor_name = str(rule.value)
                elif rule.field == "resource" and rule.value:
                    resource = str(rule.value)
                elif rule.field == "action" and rule.value:
                    action = str(rule.value)

        to_date = to_date or now
        from_date = from_date or (to_date - timedelta(days=30))
        return AuditLogQueryFilters(
            from_date=from_date,
            to_date=to_date,
            actor_id=actor_id,
            actor_name=actor_name,
            resource=resource,
            action=action,
        )

    @classmethod
    def _build_filter_query(
        cls,
        filters: FilterGroup | None,
        limit: int,
        skip: int,
        q: str | None = None,
    ) -> tuple[str, list[Any]]:
        """Construct the SQL query and parameters based on filters and search query."""
        q_filters = cls._extract_query_filters(filters)

        conditions: list[str] = ["a.created_at >= $1", "a.created_at <= $2"]
        params: list[Any] = [q_filters.from_date, q_filters.to_date]

        if q_filters.actor_id:
            params.append(q_filters.actor_id)
            conditions.append(f"a.actor_id = ${len(params)}::uuid")

        if q_filters.actor_name:
            params.append(f"%{q_filters.actor_name}%")
            conditions.append(f"(u.full_name ILIKE ${len(params)} OR u.username ILIKE ${len(params)})")

        if q_filters.resource:
            params.append(f"%{q_filters.resource}%")
            conditions.append(f"a.resource ILIKE ${len(params)}")

        if q_filters.action:
            params.append(f"%{q_filters.action}%")
            conditions.append(f"a.action ILIKE ${len(params)}")

        search_clause = _build_search_clause(params, q)
        if search_clause:
            conditions.append(search_clause)

        params.extend([limit, skip])
        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT
                a.id,
                a.actor_id,
                COALESCE(NULLIF(u.full_name, ''), u.username, 'Unknown') AS actor_name,
                u.username AS actor_username,
                u.email AS actor_email,
                a.action,
                a.resource,
                a.resource_id,
                a.details,
                a.ip_address,
                a.created_at
            FROM audit_logs a
            LEFT JOIN users u ON a.actor_id = u.id
            WHERE {where_clause}
            ORDER BY a.created_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """  # nosec B608
        return query, params

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
        Retrieve paginated list of audit logs joining users and filtering by parameters.

        Args:
            request (Request): The incoming request.
            skip (int): Number of records to skip.
            limit (int): Maximum records to return.
            q (str | None): Optional search query.
            sorts: Sorting instructions.
            filters: Filter group.

        Returns:
            Sequence[Any]: List of audit log objects.
        """
        query, params = self._build_filter_query(filters, limit, skip, q=q)
        records = await self.db.fetch(query, *params, fetch_row=False)
        if not records:
            return []
        return [self._to_admin_object(r) for r in records]

    async def count(
        self,
        request: Request,
        q: str | None = None,
        filters: FilterGroup | None = None,
    ) -> int:
        """
        Count audit logs using TimescaleDB approximate row count.

        Args:
            request (Request): The incoming request.
            q (str | None): Optional search query.
            filters: Filter group.

        Returns:
            int: Approximate total row count.
        """
        return int(await self.db.fetchval("SELECT approximate_row_count('audit_logs')"))

    async def find_by_pk(self, request: Request, pk: UUID | str) -> Any | None:
        """
        Find a single audit log by primary key joining actor details.

        Args:
            request (Request): The incoming request.
            pk (UUID | str): Primary key of the audit log.

        Returns:
            Any | None: Audit log object if found.
        """
        log_id = UUID(str(pk))
        query = """
            SELECT
                a.id,
                a.actor_id,
                COALESCE(NULLIF(u.full_name, ''), u.username, 'Unknown') AS actor_name,
                u.username AS actor_username,
                u.email AS actor_email,
                a.action,
                a.resource,
                a.resource_id,
                a.details,
                a.ip_address,
                a.created_at
            FROM audit_logs a
            LEFT JOIN users u ON a.actor_id = u.id
            WHERE a.id = $1::uuid
        """
        record = await self.db.fetch(query, log_id, fetch_row=True)
        if not record:
            return None
        return self._to_admin_object(record)

    async def find_by_pks(self, request: Request, pks: list[Any]) -> Sequence[Any]:
        """
        Find multiple audit logs by primary keys joining actor details.

        Args:
            request (Request): The incoming request.
            pks (list[Any]): Primary keys.

        Returns:
            Sequence[Any]: List of audit log objects.
        """
        if not pks:
            return []
        uuid_pks = [UUID(str(pk)) for pk in pks]
        query = """
            SELECT
                a.id,
                a.actor_id,
                COALESCE(NULLIF(u.full_name, ''), u.username, 'Unknown') AS actor_name,
                u.username AS actor_username,
                u.email AS actor_email,
                a.action,
                a.resource,
                a.resource_id,
                a.details,
                a.ip_address,
                a.created_at
            FROM audit_logs a
            LEFT JOIN users u ON a.actor_id = u.id
            WHERE a.id = ANY($1::uuid[])
            ORDER BY a.created_at DESC
        """
        records = await self.db.fetch(query, uuid_pks, fetch_row=False)
        if not records:
            return []
        return [self._to_admin_object(r) for r in records]
