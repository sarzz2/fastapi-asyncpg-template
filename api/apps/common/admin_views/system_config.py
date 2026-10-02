"""
Admin views for System Configuration.
"""

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette_admin.exceptions import ActionFailed
from starlette_admin.fields import BooleanField, DateTimeField, IntegerField, StringField
from starlette_admin.filters import FilterGroup

from api.apps.common.v0.dao.system_config import SystemConfigDAO
from api.apps.common.v0.schemas.system_config import SystemConfigData, SystemConfigUpdate
from api.core.database import DataBase
from api.utils.admin_view import BaseAppAdminView


class SystemConfigAdminView(BaseAppAdminView):
    """
    Custom Starlette-Admin view for managing singleton System Configuration via SystemConfigDAO.
    """

    key = "system_config"
    identity = "system_config"
    name = "System Configuration"
    label = "System Config"
    menu_label = "System Config"
    icon = "fa-solid fa-gears"
    pk_attr = "id"

    def can_create(self, request: Request) -> bool:
        return False

    def can_delete(self, request: Request) -> bool:
        return False

    fields = [
        IntegerField("id", label="ID", read_only=True),
        BooleanField("enforce_mfa", label="Enforce MFA"),
        DateTimeField("updated_at", label="Updated At", read_only=True),
        StringField("updated_by", label="Updated By", read_only=True),
    ]

    def __init__(self, db: DataBase) -> None:
        super().__init__()
        self.db = db
        self.dao = SystemConfigDAO(self.db)

    @staticmethod
    def _to_admin_object(config: SystemConfigData) -> SimpleNamespace:
        return SimpleNamespace(
            id=config.id,
            enforce_mfa=config.enforce_mfa,
            updated_at=config.updated_at,
            updated_by=str(config.updated_by) if config.updated_by else "-",
        )

    async def find_all(
        self,
        request: Request,
        skip: int = 0,
        limit: int = 100,
        q: str | None = None,
        sorts: Sequence[tuple[str, str]] | None = None,
        filters: FilterGroup | None = None,
    ) -> Sequence[Any]:
        config = await self.dao.get_config()
        return [self._to_admin_object(config)]

    async def count(
        self,
        request: Request,
        q: str | None = None,
        filters: FilterGroup | None = None,
    ) -> int:
        return 1

    async def find_by_pk(self, request: Request, pk: Any) -> Any:
        config = await self.dao.get_config()
        return self._to_admin_object(config)

    async def find_by_pks(self, request: Request, pks: list[Any]) -> Sequence[Any]:
        if not pks:
            return []
        config = await self.dao.get_config()
        return [self._to_admin_object(config)]

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        raise ActionFailed("Creating new system configuration is not allowed (singleton row).")

    async def delete(self, request: Request, pks: list[Any]) -> int:
        raise ActionFailed("Deleting system configuration is not allowed.")

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        try:
            update_data = SystemConfigUpdate(
                enforce_mfa=data.get("enforce_mfa"),
            )
            actor_id = getattr(request.state, "user", None)
            user_uuid = None
            if actor_id and hasattr(actor_id, "id"):
                try:
                    user_uuid = UUID(str(actor_id.id))
                except (ValueError, TypeError):
                    user_uuid = None

            updated = await self.dao.update_config(update_data, user_id=user_uuid)
            return self._to_admin_object(updated)
        except Exception as exc:
            raise ActionFailed(f"Failed to update system config: {exc}") from exc
