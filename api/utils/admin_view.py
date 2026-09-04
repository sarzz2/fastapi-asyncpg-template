"""
Base Admin View for all domain models in the application.
"""

from collections.abc import Sequence
from typing import Any

from starlette.requests import Request
from starlette_admin.filters import FilterGroup
from starlette_admin.views import BaseModelView

from api.constants import AdminConstants


class BaseAppAdminView(BaseModelView):
    """
    Base Admin View for all domain models in the application.

    Provides global configurations including:
    - Default page size = 50 for all list views.
    - Default page size options = [10, 25, 50, 100, 200].
    - Generic `repr()` implementation that dynamically extracts human-readable item labels
      (e.g., `name`, `title`, `label`, `username`, `email`) for flash messages and UI displays.
    """

    page_size = AdminConstants.DEFAULT_PAGE_SIZE
    page_size_options = AdminConstants.DEFAULT_PAGE_SIZE_OPTIONS
    additional_css_links = AdminConstants.DEFAULT_ADDITIONAL_CSS_LINKS

    async def find_all(
        self,
        request: Request,
        skip: int = 0,
        limit: int = 100,
        q: str | None = None,
        sorts: Sequence[tuple[str, str]] | None = None,
        filters: FilterGroup | None = None,
    ) -> Sequence[Any]:
        """Find all records matching criteria."""
        raise NotImplementedError

    async def count(
        self,
        request: Request,
        q: str | None = None,
        filters: FilterGroup | None = None,
    ) -> int:
        """Count total records matching criteria."""
        raise NotImplementedError

    async def find_by_pk(self, request: Request, pk: Any) -> Any | None:
        """Find a single record by primary key."""
        raise NotImplementedError

    async def find_by_pks(self, request: Request, pks: list[Any]) -> Sequence[Any]:
        """Find multiple records by primary keys."""
        raise NotImplementedError

    async def create(self, request: Request, data: dict[str, Any]) -> Any:
        """Create a new record."""
        raise NotImplementedError

    async def edit(self, request: Request, pk: Any, data: dict[str, Any]) -> Any:
        """Edit an existing record."""
        raise NotImplementedError

    async def delete(self, request: Request, pks: list[Any]) -> int:
        """Delete records by primary keys."""
        raise NotImplementedError

    async def get_pk_value(self, request: Request, obj: Any) -> Any:
        """Extract primary key value from object or dict."""
        if isinstance(obj, dict):
            return obj.get("id")
        return getattr(obj, "id", None)

    async def repr(self, obj: Any, request: Request) -> str:
        """
        Return human-readable representation of any domain object for flash messages and UI displays.

        Checks for common descriptive fields (`name`, `title`, `label`, `username`, `email`).
        Fallback is `"{ViewName} ({pk})"`.

        Args:
            obj (Any): The domain object or dictionary.
            request (Request): The incoming Starlette/FastAPI HTTP request.

        Returns:
            str: Human-readable display string.
        """
        for key in AdminConstants.DEFAULT_DISPLAY_KEYS:
            val = getattr(obj, key, None) if not isinstance(obj, dict) else obj.get(key)
            if val is not None and str(val).strip():
                return str(val)

        pk = await self.get_pk_value(request, obj)
        view_name = getattr(self, "name", None) or getattr(self, "identity", "Item")
        return f"{view_name} ({pk})"
