from uuid import uuid4

import pytest
from httpx import AsyncClient
from starlette import status

from api.apps.user.schemas.role import RoleCreate
from api.apps.user.v0.dao.role import RoleDAO
from api.apps.user.v0.dao.user import UserDAO
from api.core.database import DataBase
from api.core.redis import redis_client
from api.shared.redis_keys import RedisKeys


async def _setup_admin_with_perms(client: AsyncClient, db: DataBase, short_id: str, email: str, password: str) -> dict:
    """Helper to setup admin user with permissions"""
    user_dao = UserDAO(db)
    role_dao = RoleDAO(db)

    # Register
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Admin User"},
    )
    admin_user = await user_dao.get_by_email(email)
    assert admin_user is not None

    # Create required permissions
    perms = ["roles:read", "roles:create"]
    perm_ids = []
    for p in perms:
        await db.execute(
            "INSERT INTO permissions (name, description) VALUES ($1, 'Test Perm') "
            "ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description RETURNING id",
            p,
        )
        rec = await db.fetch("SELECT id FROM permissions WHERE name = $1", p, fetch_row=True)
        assert rec is not None
        perm_ids.append(rec["id"])

    # Create admin role and assign
    admin_role = await role_dao.create_role(
        RoleCreate(name=f"Admin_{short_id}", description="Admin Role", permission_ids=perm_ids)
    )
    await user_dao.assign_roles(admin_user.id, [admin_role.id])

    # Login
    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    token = login_response.json()["token"]["access_token"]

    return {"token": token, "user": admin_user}


@pytest.mark.asyncio
async def test_role_lifecycle(client: AsyncClient) -> None:  # pylint: disable=too-many-locals,too-many-statements
    """
    Test the full lifecycle for roles: creation, retrieval (miss/hit), update (invalidation), and deletion.
    """
    # Setup: Create Admin User with permissions
    db = DataBase()
    role_dao = RoleDAO(db)
    user_dao = UserDAO(db)

    short_id = uuid4().hex[:8]
    email = f"admin_{short_id}@test.com"
    password = "password123"

    # 1. Register Admin
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Admin User"},
    )
    admin_user = await user_dao.get_by_email(email)
    assert admin_user is not None

    # 2. Create permissions
    perms = ["roles:create", "roles:read", "roles:update", "roles:delete"]
    perm_ids = []
    for p in perms:
        await db.execute(
            "INSERT INTO permissions (name, description) VALUES ($1, 'Test Perm') "
            "ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description RETURNING id",
            p,
        )
        rec = await db.fetch("SELECT id FROM permissions WHERE name = $1", p, fetch_row=True)
        assert rec is not None
        perm_ids.append(rec["id"])

    # 3. Create Admin Role
    admin_role = await role_dao.create_role(
        RoleCreate(name=f"Admin_{short_id}", description="Admin Role", permission_ids=perm_ids)
    )

    # 4. Assign Role to Admin
    await user_dao.assign_roles(admin_user.id, [admin_role.id])

    # 5. Login
    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    assert login_response.status_code == 200
    admin_token = login_response.json()["token"]["access_token"]

    # --- Test Flow ---

    # 1. Create a role
    role_data = {"name": f"cache_test_role_{short_id}", "description": "Role for testing caching", "permission_ids": []}
    response = await client.post("/api/v0/roles", json=role_data, headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == status.HTTP_201_CREATED
    role_id = response.json()["id"]

    # 2. Get the role (First call - Cache Miss)
    response = await client.get(f"/api/v0/roles/{role_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == status.HTTP_200_OK

    # Check if key exists in Redis (Hash Field)
    # key = RedisKeys.ROLE_BY_ID.format(role_id=role_id) -> Now it's a field in ROLES_CACHE
    field = RedisKeys.ROLE_FIELD_BY_ID.format(role_id=role_id)
    cached_val = await redis_client.client.hget(RedisKeys.ROLES_CACHE, field)  # type: ignore
    assert cached_val is not None

    # Check TTL
    ttl = await redis_client.client.ttl(RedisKeys.ROLES_CACHE)
    assert ttl > 0

    # 3. Get the role again (Second call - Cache Hit)
    response = await client.get(f"/api/v0/roles/{role_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == status.HTTP_200_OK

    # 4. Update the role
    update_data = {"description": "Updated description"}
    response = await client.patch(
        f"/api/v0/roles/{role_id}", json=update_data, headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == status.HTTP_200_OK

    # Check if key is invalidated (Cache should be empty)
    # Since update_role uses _get_role_by_id (uncached) and invalidates, the cache is cleared.
    cached_val = await redis_client.client.hget(RedisKeys.ROLES_CACHE, field)  # type: ignore
    assert cached_val is None

    # 5. Get the role (Refill Cache)
    response = await client.get(f"/api/v0/roles/{role_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["description"] == "Updated description"

    cached_val = await redis_client.client.hget(RedisKeys.ROLES_CACHE, field)  # type: ignore
    assert cached_val is not None

    # 6. Delete the role
    response = await client.delete(f"/api/v0/roles/{role_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == status.HTTP_204_NO_CONTENT

    # Check if key is deleted
    cached_val = await redis_client.client.hget(RedisKeys.ROLES_CACHE, field)  # type: ignore
    assert cached_val is None


@pytest.mark.asyncio
async def test_role_pagination(client: AsyncClient) -> None:
    """
    Test cursor-based pagination for roles and permissions.
    """
    # Setup: Create Admin User
    db = DataBase()
    role_dao = RoleDAO(db)

    short_id = uuid4().hex[:8]
    email = f"admin_pag_{short_id}@test.com"
    password = "password123"

    # Setup: Create Admin User and Role logic extracted
    admin_setup = await _setup_admin_with_perms(client, db, short_id, email, password)
    admin_token = admin_setup["token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Create multiple roles for pagination testing
    # Create 5 roles
    for i in range(5):
        await role_dao.create_role(
            RoleCreate(name=f"PagRole_{i}_{short_id}", description=f"Pagination Role {i}", permission_ids=[])
        )

    # 2. Test List Roles Pagination

    # Page 1: First 2 roles
    resp = await client.get("/api/v0/roles?first=2", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["page_info"]["end_cursor"] is not None
    cursor = data["page_info"]["end_cursor"]

    # Page 2: Next 2 roles
    resp = await client.get(f"/api/v0/roles?first=2&after={cursor}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["page_info"]["end_cursor"] is not None

    # 3. Test List Permissions Pagination (Assuming perms exist from setup)
    resp = await client.get("/api/v0/roles/permissions?first=1", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["page_info"]["end_cursor"] is not None
