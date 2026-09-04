"""
Main Admin Dashboard View for Starlette-Admin portal.
"""

import logging
from typing import Any

from starlette.requests import Request
from starlette_admin.views import CustomView
from starlette_admin.widgets import CardRowWidget, ColumnWidget, PanelWidget, StatWidget, TableWidget

from api.core.database import DataBase

logger = logging.getLogger("fastapi")


class DashboardView(CustomView):
    """
    Main interactive dashboard view displaying key metrics, quick links,
    and recent activity tables for the application.
    """

    def __init__(self, db: DataBase) -> None:
        """
        Initialize DashboardView with shared DataBase connection instance.

        Args:
            db (DataBase): Database connection instance.
        """
        super().__init__(
            menu_label="Dashboard",
            icon="fa-solid fa-gauge-high",
            route_name="index",
            add_to_menu=True,
            widget=self._build_dashboard_widget,
        )
        self.db = db

    async def _get_total_users(self, _request: Request) -> int:
        """
        Fetch total registered users count.

        Args:
            _request (Request): The incoming Starlette/FastAPI HTTP request.

        Returns:
            int: Total count of user records.
        """
        try:
            record = await self.db.fetch("SELECT COUNT(*) as cnt FROM users", fetch_row=True)
            return int(record["cnt"]) if record else 0
        except Exception as err:  # pylint: disable=broad-exception-caught
            logger.exception("Error fetching total users for dashboard: %s", err)
            return 0

    async def _get_active_users(self, _request: Request) -> int:
        """
        Fetch active users count.

        Args:
            _request (Request): The incoming Starlette/FastAPI HTTP request.

        Returns:
            int: Total count of active user records.
        """
        try:
            record = await self.db.fetch("SELECT COUNT(*) as cnt FROM users WHERE is_active = true", fetch_row=True)
            return int(record["cnt"]) if record else 0
        except Exception as err:  # pylint: disable=broad-exception-caught
            logger.exception("Error fetching active users for dashboard: %s", err)
            return 0

    async def _get_total_roles(self, _request: Request) -> int:
        """
        Fetch total roles count.

        Args:
            _request (Request): The incoming Starlette/FastAPI HTTP request.

        Returns:
            int: Total count of active role records.
        """
        try:
            record = await self.db.fetch("SELECT COUNT(*) as cnt FROM roles WHERE is_deleted = false", fetch_row=True)
            return int(record["cnt"]) if record else 0
        except Exception as err:  # pylint: disable=broad-exception-caught
            logger.exception("Error fetching total roles for dashboard: %s", err)
            return 0

    async def _get_total_permissions(self, _request: Request) -> int:
        """
        Fetch total permissions count.

        Args:
            _request (Request): The incoming Starlette/FastAPI HTTP request.

        Returns:
            int: Total count of permission records.
        """
        try:
            record = await self.db.fetch("SELECT COUNT(*) as cnt FROM permissions", fetch_row=True)
            return int(record["cnt"]) if record else 0
        except Exception as err:  # pylint: disable=broad-exception-caught
            logger.exception("Error fetching total permissions for dashboard: %s", err)
            return 0

    async def _get_recent_roles_table(self, _request: Request) -> list[list[Any]]:
        """
        Fetch recent roles for dashboard summary table.

        Args:
            _request (Request): The incoming Starlette/FastAPI HTTP request.

        Returns:
            list[list[Any]]: Formatted 2D array of role rows for TableWidget.
        """
        try:
            query = """
                SELECT name, description, created_at
                FROM roles
                WHERE is_deleted = false
                ORDER BY created_at DESC
                LIMIT 5
            """
            records = await self.db.fetch(query, fetch_row=False)
            if not records:
                return []
            return [
                [
                    r["name"],
                    r["description"] or "-",
                    r["created_at"].strftime("%Y-%m-%d %H:%M") if r.get("created_at") else "-",
                ]
                for r in records
            ]
        except Exception as err:  # pylint: disable=broad-exception-caught
            logger.exception("Error fetching recent roles for dashboard: %s", err)
            return []

    async def _build_dashboard_widget(self, _request: Request) -> ColumnWidget:
        """
        Construct responsive dashboard layout containing stat metrics and summary table widgets.

        Args:
            request (Request): The incoming Starlette/FastAPI HTTP request.

        Returns:
            ColumnWidget: Root widget layout tree for dashboard index view.
        """
        stat_users = StatWidget(
            title="Total Users",
            value_callback=self._get_total_users,
            description="Registered account profiles",
            color="primary",
            countup=True,
        )

        stat_active_users = StatWidget(
            title="Active Users",
            value_callback=self._get_active_users,
            description="Verified active user accounts",
            color="success",
            countup=True,
        )

        stat_roles = StatWidget(
            title="Roles",
            value_callback=self._get_total_roles,
            link="/admin/role/list",
            description="Configured access roles",
            color="info",
            countup=True,
        )

        stat_permissions = StatWidget(
            title="Permissions",
            value_callback=self._get_total_permissions,
            description="System permission grants",
            color="warning",
            countup=True,
        )

        stats_row = CardRowWidget(children=[stat_users, stat_active_users, stat_roles, stat_permissions])

        roles_table = TableWidget(
            title="Recent System Roles",
            columns=["Role Name", "Description", "Created At"],
            rows_callback=self._get_recent_roles_table,
        )

        overview_panel = PanelWidget(
            title="System Overview",
            icon="fa-solid fa-layer-group",
            children=[roles_table],
        )

        return ColumnWidget(children=[stats_row, overview_panel])
