from typing import Tuple
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from api.apps.user.schemas.role import RoleCreate, RoleUpdate
from api.apps.user.v0.dao.role import RoleDAO
from api.apps.user.v0.dao.user import UserDAO
from api.core.database import DataBase


async def register_and_login(client: AsyncClient, prefix: str = "test") -> Tuple[str, str, str]:
    """
    Helper to register and login a test user.
    Returns (user_id, email, access_token).
    """
    short_id = uuid4().hex[:8]
    email = f"{prefix}_{short_id}@example.com"
    password = "Str0ngP@ssw0rd!123"

    reg_resp = await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": f"{prefix.capitalize()} User"},
    )
    assert reg_resp.status_code == 201
    user_id = reg_resp.json()["id"]

    login_resp = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]["access_token"]

    return user_id, email, token


@pytest.mark.asyncio
async def test_list_sessions(client: AsyncClient) -> None:
    """
    Verify that authenticated users can retrieve their active sessions.
    """
    user_id, _, token = await register_and_login(client, "session")
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/v0/users/sessions", headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["user_id"] == user_id


@pytest.mark.asyncio
async def test_list_sessions_pagination(client: AsyncClient) -> None:
    """
    Verify cursor-based pagination for the session listing endpoint.
    """
    _, email, _ = await register_and_login(client, "sess_pag")
    password = "Str0ngP@ssw0rd!123"

    # Create 4 additional sessions (total 5)
    tokens = []
    for i in range(4):
        resp = await client.post(
            "/api/v0/auth/login", json={"username": email, "password": password}, headers={"User-Agent": f"Agent-{i}"}
        )
        assert resp.status_code == 200
        tokens.append(resp.json()["token"]["access_token"])

    headers = {"Authorization": f"Bearer {tokens[-1]}"}

    # Iterate through pages
    response = await client.get("/api/v0/users/sessions?limit=2", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2

    next_cursor = data["next_cursor"]
    response = await client.get(f"/api/v0/users/sessions?limit=2&cursor={next_cursor}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2

    next_cursor = data["next_cursor"]
    response = await client.get(f"/api/v0/users/sessions?limit=2&cursor={next_cursor}", headers=headers)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient) -> None:
    """
    Verify that /users/me returns the correct profile for the authenticated user.
    """
    _, email, token = await register_and_login(client, "me")
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/v0/users/me", headers=headers)
    assert response.status_code == 200

    user_data = response.json()
    assert user_data["email"] == email
    assert "Me User" in user_data["full_name"]


@pytest.mark.asyncio
async def test_update_user(client: AsyncClient) -> None:
    """
    Verify that users can update their profile information.
    """
    _, _, token = await register_and_login(client, "update")
    headers = {"Authorization": f"Bearer {token}"}
    new_name = "Refactored Name"

    # Update name
    response = await client.patch("/api/v0/users/", json={"full_name": new_name}, headers=headers)
    assert response.status_code == 200
    assert response.json()["full_name"] == new_name

    # Cross-verify with GET /me
    response = await client.get("/api/v0/users/me", headers=headers)
    assert response.json()["full_name"] == new_name


@pytest.mark.asyncio
async def test_revoke_session_invalidation(client: AsyncClient) -> None:
    """
    Verify that revoking a session immediately invalidates the associated token.
    """
    _, _, token = await register_and_login(client, "revoke")
    headers = {"Authorization": f"Bearer {token}"}

    # Get JTI
    sessions_resp = await client.get("/api/v0/users/sessions", headers=headers)
    jti = sessions_resp.json()["items"][0]["jti"]

    # Revoke
    response = await client.delete(f"/api/v0/users/sessions/{jti}", headers=headers)
    assert response.status_code == 204

    # Verify access is now denied
    response = await client.get("/api/v0/users/me", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_access_denied_after_revocation(client: AsyncClient) -> None:
    """
    Verify that all protected endpoints are inaccessible after session revocation.
    """
    _, _, token = await register_and_login(client, "revoke_all")
    headers = {"Authorization": f"Bearer {token}"}

    sessions_resp = await client.get("/api/v0/users/sessions", headers=headers)
    jti = sessions_resp.json()["items"][0]["jti"]

    await client.delete(f"/api/v0/users/sessions/{jti}", headers=headers)

    # Check multiple endpoints
    endpoints = [
        ("GET", "/api/v0/users/me", None),
        ("GET", "/api/v0/users/sessions", None),
        ("PATCH", "/api/v0/users/", {"full_name": "Ghost"}),
    ]

    for method, url, body in endpoints:
        response = await client.request(method, url, json=body, headers=headers)
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_update_scenarios(client: AsyncClient) -> None:
    """
    Verify error handling for invalid user update requests.
    """
    await register_and_login(client, "invalid_up")

    # Missing Auth
    response = await client.patch("/api/v0/users/", json={"full_name": "No Auth"})
    assert response.status_code == 401

    # Malformed Token
    invalid_headers = {"Authorization": "Bearer DefinitelyNotAToken"}
    response = await client.patch("/api/v0/users/", json={"full_name": "X"}, headers=invalid_headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_revoke_nonexistent_session(client: AsyncClient) -> None:
    """
    Verify that attempting to revoke a non-existent session returns 404.
    """
    _, _, token = await register_and_login(client, "nonexist")
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.delete("/api/v0/users/sessions/fake_jti_999", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_revoke_others_session(client: AsyncClient) -> None:
    """
    Verify that users cannot revoke sessions belonging to other users.
    """
    # Create two users
    _, _, token1 = await register_and_login(client, "user1")
    _, _, token2 = await register_and_login(client, "user2")

    # User 1 session info
    headers1 = {"Authorization": f"Bearer {token1}"}
    sessions1 = await client.get("/api/v0/users/sessions", headers=headers1)
    jti1 = sessions1.json()["items"][0]["jti"]

    # User 2 tries to revoke user 1's session
    headers2 = {"Authorization": f"Bearer {token2}"}
    response = await client.delete(f"/api/v0/users/sessions/{jti1}", headers=headers2)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_assign_role_permission(client: AsyncClient) -> None:  # pylint: disable=too-many-locals
    """
    Verify role assignment flow between an admin and a target user.
    """
    db = DataBase()
    try:
        user_dao = UserDAO(db)
        role_dao = RoleDAO(db)
        short_id = uuid4().hex[:8]

        # Setup Admin and Target
        admin_id, admin_email, admin_token = await register_and_login(client, "admin")
        target_id, _, _ = await register_and_login(client, "target")

        # Grant 'users:update' to Admin via DB override for testing
        await db.execute(
            "INSERT INTO permissions (name, description) VALUES ('users:update', 'Update users') ON CONFLICT DO NOTHING"
        )
        perm = await db.fetch("SELECT id FROM permissions WHERE name = 'users:update'", fetch_row=True)
        assert perm is not None

        admin_role = await role_dao.create_role(RoleCreate(name=f"AdminRole_{short_id}", permission_ids=[perm["id"]]))
        await user_dao.assign_roles(UUID(admin_id), [admin_role.id])

        # Re-login to obtain token with new 'users:update' scope and correct token_version
        login_resp = await client.post(
            "/api/v0/auth/login", json={"username": admin_email, "password": "Str0ngP@ssw0rd!123"}
        )
        admin_token = login_resp.json()["token"]["access_token"]

        # Create target role to be assigned
        new_role = await role_dao.create_role(RoleCreate(name=f"NewRole_{short_id}"))

        # Execute assignment via API
        headers = {"Authorization": f"Bearer {admin_token}"}
        endpoint = f"/api/v0/users/{target_id}/roles"
        response = await client.post(endpoint, json={"role_ids": [str(new_role.id)]}, headers=headers)
        assert response.status_code == 204

        # Verify persistence
        updated_target = await user_dao.get_by_id(UUID(target_id))
        assert updated_target is not None
        assert new_role.id in [r.id for r in updated_target.roles]

    finally:
        await db.close_pool()


@pytest.mark.asyncio
async def test_token_version_increment_on_sensitive_changes(client: AsyncClient) -> None:
    """
    Verify that token_version increments upon password updates or role assignments.
    """
    db = DataBase()
    try:
        user_dao = UserDAO(db)
        role_dao = RoleDAO(db)

        user_id, email, _ = await register_and_login(client, "token_ver")
        user = await user_dao.get_by_email(email)
        assert user is not None
        v1 = user.token_version

        # Password update
        await user_dao.update_password(UUID(user_id), "new_secure_hash")
        user = await user_dao.get_by_id(UUID(user_id))
        assert user is not None
        v2 = user.token_version
        assert v2 > v1

        # Role assignment
        role = await role_dao.create_role(RoleCreate(name="Role_TokenVer"))
        await user_dao.assign_roles(UUID(user_id), [role.id])
        user = await user_dao.get_by_id(UUID(user_id))
        assert user is not None
        assert user.token_version > v2

    finally:
        await db.close_pool()


@pytest.mark.asyncio
async def test_bulk_token_invalidation_on_role_update(client: AsyncClient) -> None:
    """
    Verify that updating a role's permissions increments token_version for all affected users.
    """
    db = DataBase()
    try:
        user_dao = UserDAO(db)
        role_dao = RoleDAO(db)

        user_id, email, _ = await register_and_login(client, "role_bulk")
        user = await user_dao.get_by_email(email)
        assert user is not None

        # Assign role
        role = await role_dao.create_role(RoleCreate(name="BulkRole"))
        await user_dao.assign_roles(UUID(user_id), [role.id])

        user = await user_dao.get_by_id(UUID(user_id))
        assert user is not None
        version_before = user.token_version

        # Update the role itself
        await db.execute("INSERT INTO permissions (name, description) VALUES ('p1', 'd1') ON CONFLICT DO NOTHING")
        perm = await db.fetch("SELECT id FROM permissions WHERE name = 'p1'", fetch_row=True)
        assert perm is not None
        await role_dao.update_role(role.id, RoleUpdate(permission_ids=[perm["id"]]))

        # Verify user version was bumped
        updated_user = await user_dao.get_by_id(UUID(user_id))
        assert updated_user is not None
        assert updated_user.token_version > version_before

    finally:
        await db.close_pool()
