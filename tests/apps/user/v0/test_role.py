# pylint: disable=duplicate-code  # Shared user-registration pattern across test modules is intentional
from uuid import uuid4

import pytest
from httpx import AsyncClient
from starlette import status

from api.apps.user.v0.dao.role import RoleDAO
from api.apps.user.v0.dao.user import UserDAO
from api.apps.user.v0.schemas.role import RoleCreate
from api.core.database import DataBase
from api.core.redis import redis_client
from api.shared.redis_keys import RedisKeys


async def setup_admin_user(client: AsyncClient, db: DataBase, prefix: str = "admin") -> dict:
    """
    Helper to setup an admin user with roles and permissions required for management.
    """
    short_id = uuid4().hex[:8]
    email = f"{prefix}_{short_id}@example.com"
    password = "Str0ngP@ssw0rd!123"

    # Register
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Admin Manager"},
    )
    user = await UserDAO(db).get_by_email(email)

    # Setup permissions
    perms = ["roles:create", "roles:read", "roles:update", "roles:delete"]
    perm_ids = []
    for p_name in perms:
        await db.execute(
            "INSERT INTO permissions (name, description) VALUES ($1, 'Test Perm') ON CONFLICT (name) DO NOTHING", p_name
        )
        rec = await db.fetch("SELECT id FROM permissions WHERE name = $1", p_name, fetch_row=True)
        assert rec is not None
        perm_ids.append(rec["id"])

    # Create and assign role
    admin_role = await RoleDAO(db).create_role(RoleCreate(name=f"AdminRole_{short_id}", permission_ids=perm_ids))
    assert user is not None
    await UserDAO(db).assign_roles(user.id, [admin_role.id])

    # Login
    login_resp = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    token = login_resp.json()["token"]["access_token"]
    assert user is not None
    return {"token": token, "user_id": user.id, "short_id": short_id}


@pytest.mark.asyncio
async def test_role_lifecycle_and_caching(client: AsyncClient) -> None:
    """
    Verify the full lifecycle of a role, including CRUD operations and Redis cache invalidation.
    """
    db = DataBase()
    try:
        setup = await setup_admin_user(client, db, "lifecycle")
        token = setup["token"]
        headers = {"Authorization": f"Bearer {token}"}
        short_id = setup["short_id"]

        # 1. Create Role
        role_payload = {"name": f"test_role_{short_id}", "description": "Cache Test"}
        response = await client.post("/api/v0/roles", json=role_payload, headers=headers)
        assert response.status_code == status.HTTP_201_CREATED
        role_id = response.json()["id"]

        # 2. Verify Cache Population on GET
        field = RedisKeys.ROLE_FIELD_BY_ID.format(role_id=role_id)
        # Ensure it starts empty in cache
        await redis_client.client.hdel(RedisKeys.ROLES_CACHE, field)

        await client.get(f"/api/v0/roles/{role_id}", headers=headers)
        cached_val = await redis_client.client.hget(RedisKeys.ROLES_CACHE, field)
        assert cached_val is not None

        # 3. Verify Cache Invalidation on Update
        await client.patch(f"/api/v0/roles/{role_id}", json={"description": "Updated"}, headers=headers)
        assert await redis_client.client.hget(RedisKeys.ROLES_CACHE, field) is None

        # 4. Cleanup on Delete
        await client.get(f"/api/v0/roles/{role_id}", headers=headers)  # Repopulate
        await client.delete(f"/api/v0/roles/{role_id}", headers=headers)
        assert await redis_client.client.hget(RedisKeys.ROLES_CACHE, field) is None

    finally:
        await db.close_pool()


@pytest.mark.asyncio
async def test_role_and_permission_pagination(client: AsyncClient) -> None:
    """
    Verify cursor-based pagination for listing roles and permissions.
    """
    db = DataBase()
    try:
        setup = await setup_admin_user(client, db, "pag")
        token = setup["token"]
        headers = {"Authorization": f"Bearer {token}"}
        role_dao = RoleDAO(db)

        # Batch create roles
        for i in range(5):
            await role_dao.create_role(RoleCreate(name=f"PagRole_{i}_{setup['short_id']}"))

        # Test Roles Pagination
        resp = await client.get("/api/v0/roles?first=2", headers=headers)
        data = resp.json()
        assert len(data["items"]) == 2
        cursor = data["page_info"]["end_cursor"]

        resp = await client.get(f"/api/v0/roles?first=2&after={cursor}", headers=headers)
        assert len(resp.json()["items"]) == 2

        # Test Permissions Pagination
        resp = await client.get("/api/v0/roles/permissions?first=1", headers=headers)
        assert len(resp.json()["items"]) == 1

    finally:
        await db.close_pool()
