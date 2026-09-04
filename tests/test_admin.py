"""
Tests for Starlette-Admin integration and custom RoleAdminView.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette_admin.auth import AdminUser

from api.main import app


@pytest.mark.asyncio
async def test_admin_unauthenticated_redirect() -> None:
    """Verify that unauthenticated GET request to /admin redirects to login."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as client:
        response = await client.get("/admin/")
        assert response.status_code in [302, 303, 307]
        assert "/admin/login" in response.headers.get("location", "")


@pytest.mark.asyncio
async def test_admin_login_page_renders() -> None:
    """Verify that GET request to /admin/login returns 200 OK with HTML login form."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/login")
        assert response.status_code == 200
        assert "username" in response.text.lower() or "password" in response.text.lower()


def test_admin_login_failed() -> None:
    """Verify that invalid credentials on login form submission returns error status."""
    with (
        patch("api.core.admin.UserDAO.get_by_email", new_callable=AsyncMock) as mock_get_email,
        patch("api.core.admin.UserDAO.get_by_username", new_callable=AsyncMock) as mock_get_username,
    ):
        mock_get_email.return_value = None
        mock_get_username.return_value = None

        client = TestClient(app)
        get_resp = client.get("/admin/login")
        assert get_resp.status_code == 200
        csrf_token = get_resp.cookies.get("starlette_admin_csrftoken", "")

        response = client.post(
            "/admin/login",
            data={"username": "wrong@example.com", "password": "wrongpassword", "csrftoken": csrf_token},
            headers={"X-CSRFToken": csrf_token},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_role_admin_view_list_route() -> None:
    """Verify that authenticated request to /admin/role/list renders list page."""
    with (
        patch("api.core.admin.AdminAuthProvider.authenticate", new_callable=AsyncMock) as mock_auth,
        patch("api.apps.user.admin_views.role.RoleAdminView.count", new_callable=AsyncMock) as mock_count,
        patch("api.apps.user.admin_views.role.RoleAdminView.find_all", new_callable=AsyncMock) as mock_find_all,
    ):
        mock_auth.return_value = AdminUser(username="Super Admin")
        mock_count.return_value = 0
        mock_find_all.return_value = []

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/admin/role/list")
            assert response.status_code == 200
            assert "Roles" in response.text


@pytest.mark.asyncio
async def test_admin_dashboard_index_route() -> None:
    """Verify that authenticated request to /admin/ renders dashboard page."""
    with patch("api.core.admin.AdminAuthProvider.authenticate", new_callable=AsyncMock) as mock_auth:
        mock_auth.return_value = AdminUser(username="Super Admin")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/admin/")
            assert response.status_code == 200
            assert "Dashboard" in response.text


@pytest.mark.asyncio
async def test_user_admin_view_list_route() -> None:
    """Verify that authenticated request to /admin/user/list renders list page."""
    with (
        patch("api.core.admin.AdminAuthProvider.authenticate", new_callable=AsyncMock) as mock_auth,
        patch("api.apps.user.admin_views.user.UserAdminView.count", new_callable=AsyncMock) as mock_count,
        patch("api.apps.user.admin_views.user.UserAdminView.find_all", new_callable=AsyncMock) as mock_find_all,
    ):
        mock_auth.return_value = AdminUser(username="Super Admin")
        mock_count.return_value = 0
        mock_find_all.return_value = []

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/admin/user/list")
            assert response.status_code == 200
            assert "Users" in response.text


@pytest.mark.asyncio
async def test_periodic_task_admin_view_list_route() -> None:
    """Verify that authenticated request to /admin/periodic_task/list renders list page."""
    with (
        patch("api.core.admin.AdminAuthProvider.authenticate", new_callable=AsyncMock) as mock_auth,
        patch(
            "api.apps.common.admin_views.periodic_task.PeriodicTaskAdminView.count", new_callable=AsyncMock
        ) as mock_count,
        patch(
            "api.apps.common.admin_views.periodic_task.PeriodicTaskAdminView.find_all", new_callable=AsyncMock
        ) as mock_find_all,
    ):
        mock_auth.return_value = AdminUser(username="Super Admin")
        mock_count.return_value = 0
        mock_find_all.return_value = []

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/admin/periodic_task/list")
            assert response.status_code == 200
            assert "Periodic Tasks" in response.text
