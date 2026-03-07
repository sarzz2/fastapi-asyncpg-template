from uuid import uuid4

import pytest
from httpx import AsyncClient

from api.apps.user.schemas.role import RoleCreate, RoleUpdate
from api.apps.user.v0.dao.role import RoleDAO
from api.apps.user.v0.dao.user import UserDAO
from api.core.database import DataBase


@pytest.mark.asyncio
async def test_list_sessions(client: AsyncClient) -> None:
    """Test listing user sessions.

    Verifies that authenticated users can retrieve a list of their active sessions.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a new user
        2. Login to create a session
        3. List sessions and verify the session is returned
        4. Verify the session belongs to the correct user
    """
    short_id = uuid4().hex[:8]
    email = f"sess_{short_id}@test.com"
    password = "Str0ngP@ssw0rd!2"
    response = await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Session User"},
    )
    assert response.status_code == 201
    user_id = response.json()["id"]

    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    assert login_response.status_code == 200
    token = login_response.json()["token"]["access_token"]

    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get("/api/v0/users/sessions", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["user_id"] == user_id


@pytest.mark.asyncio
async def test_list_sessions_pagination(client: AsyncClient) -> None:
    """Test session listing with cursor-based pagination.

    Verifies that the session listing endpoint properly implements cursor-based
    pagination, allowing users to retrieve sessions in pages.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a new user
        2. Login multiple times with different user agents to create 5 sessions
        3. Retrieve page 1 with limit=2, verify 2 items returned
        4. Retrieve page 2 using cursor, verify 2 items returned
        5. Retrieve page 3 using cursor, verify 1 item returned (last page)

    Note:
        Different user agents are used because upsert_user_session updates
        existing sessions if the user_agent matches.
    """
    short_id = uuid4().hex[:8]
    email = f"sess_pag_{short_id}@test.com"
    password = "Str0ngP@ssw0rd!2"
    response = await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Session Pagination User"},
    )
    assert response.status_code == 201

    tokens = []
    for i in range(5):
        login_response = await client.post(
            "/api/v0/auth/login", json={"username": email, "password": password}, headers={"User-Agent": f"Agent-{i}"}
        )
        assert login_response.status_code == 200
        tokens.append(login_response.json()["token"]["access_token"])

    headers = {"Authorization": f"Bearer {tokens[-1]}"}

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
    data = response.json()
    assert len(data["items"]) == 1


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient) -> None:
    """Test getting current user information.

    Verifies that authenticated users can retrieve their own profile information.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a new user
        2. Login to obtain access token
        3. Call /users/me endpoint
        4. Verify returned user data matches registration data
    """
    short_id = uuid4().hex[:8]
    email = f"me_{short_id}@test.com"
    password = "Str0ngP@ssw0rd!1"
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Me User"},
    )
    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    token = login_response.json()["token"]["access_token"]

    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get("/api/v0/users/me", headers=headers)
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["email"] == email
    assert user_data["full_name"] == "Me User"


@pytest.mark.asyncio
async def test_update_user(client: AsyncClient) -> None:
    """Test updating user profile information.

    Verifies that authenticated users can update their profile information
    and that the changes are persisted.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a new user
        2. Login to obtain access token
        3. Update user's full_name via PATCH /users/
        4. Verify the update response contains the new name
        5. Verify the change persists by calling GET /users/me
    """
    short_id = uuid4().hex[:8]
    email = f"update_{short_id}@test.com"
    password = "Str0ngP@ssw0rd!1"
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Update User"},
    )
    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    token = login_response.json()["token"]["access_token"]

    headers = {"Authorization": f"Bearer {token}"}
    new_name = "Updated Name"
    response = await client.patch("/api/v0/users/", json={"full_name": new_name}, headers=headers)
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["full_name"] == new_name

    response = await client.get("/api/v0/users/me", headers=headers)
    assert response.json()["full_name"] == new_name


@pytest.mark.asyncio
async def test_revoke_session(client: AsyncClient) -> None:
    """Test revoking a user session by JTI.

    Verifies that users can revoke their own sessions and that the revoked
    session's token becomes invalid immediately.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a new user and login
        2. Retrieve the session JTI from the sessions list
        3. Revoke the session using DELETE /users/sessions/{jti}
        4. Verify the token is immediately blacklisted and rejected

    Note:
        The token blacklist check happens in verify_token. Revoked sessions
        may still appear in the sessions list depending on implementation,
        but the tokens are immediately invalidated.
    """
    short_id = uuid4().hex[:8]
    email = f"revoke_{short_id}@test.com"
    password = "Str0ngP@ssw0rd!1"
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Revoke User"},
    )
    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    token = login_response.json()["token"]["access_token"]

    headers = {"Authorization": f"Bearer {token}"}
    sessions_resp = await client.get("/api/v0/users/sessions", headers=headers)
    jti = sessions_resp.json()["items"][0]["jti"]

    response = await client.delete(f"/api/v0/users/sessions/{jti}", headers=headers)
    assert response.status_code == 204

    response = await client.get("/api/v0/users/me", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_access_after_revoke_session(client: AsyncClient) -> None:
    """Test that all endpoints are inaccessible after session revocation.

    Verifies that revoking a session immediately invalidates the token across
    all protected endpoints, not just the /users/me endpoint.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a new user and login
        2. Verify access works before revocation
        3. Revoke the session
        4. Verify all protected endpoints reject the token with 401
    """
    short_id = uuid4().hex[:8]
    email = f"revoke_access_{short_id}@test.com"
    password = "Str0ngP@ssw0rd!1"
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Revoke Access User"},
    )
    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    token = login_response.json()["token"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/v0/users/me", headers=headers)
    assert response.status_code == 200

    sessions_resp = await client.get("/api/v0/users/sessions", headers=headers)
    jti = sessions_resp.json()["items"][0]["jti"]
    response = await client.delete(f"/api/v0/users/sessions/{jti}", headers=headers)
    assert response.status_code == 204

    response = await client.get("/api/v0/users/me", headers=headers)
    assert response.status_code == 401

    response = await client.get("/api/v0/users/sessions", headers=headers)
    assert response.status_code == 401

    response = await client.patch("/api/v0/users/", json={"full_name": "New Name"}, headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_update_user(client: AsyncClient) -> None:
    """Test invalid user update scenarios.

    Verifies that the user update endpoint properly validates authentication
    and handles invalid tokens.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a new user and login
        2. Attempt to update with empty full_name (may be allowed or rejected)
        3. Attempt to update without authentication token
        4. Attempt to update with invalid authentication token
        5. Verify all unauthorized requests are rejected with 401
    """
    short_id = uuid4().hex[:8]
    email = f"invalid_update_{short_id}@test.com"
    password = "Str0ngP@ssw0rd!1"
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Invalid Update User"},
    )
    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    token = login_response.json()["token"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.patch("/api/v0/users/", json={"full_name": ""}, headers=headers)
    assert response.status_code in [200, 422]

    response = await client.patch("/api/v0/users/", json={"full_name": "No Auth"})
    assert response.status_code == 401

    invalid_headers = {"Authorization": "Bearer invalid_token_here"}
    response = await client.patch("/api/v0/users/", json={"full_name": "Invalid Token"}, headers=invalid_headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_revoke_nonexistent_session(client: AsyncClient) -> None:
    """Test revoking a session that doesn't exist.

    Verifies that attempting to revoke a non-existent session returns 404.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register and login a user
        2. Attempt to revoke a session with a non-existent JTI
        3. Verify 404 response is returned
    """
    short_id = uuid4().hex[:8]
    email = f"revoke_nonexist_{short_id}@test.com"
    password = "Str0ngP@ssw0rd!1"
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Revoke Test"},
    )
    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    token = login_response.json()["token"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Try to revoke a non-existent session
    fake_jti = "non_existent_jti_12345"
    response = await client.delete(f"/api/v0/users/sessions/{fake_jti}", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_revoke_another_users_session(client: AsyncClient) -> None:
    """Test that users cannot revoke other users' sessions.

    Verifies that attempting to revoke another user's session returns 404
    (session not found for the current user).

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Create two users
        2. Get session JTI from user1
        3. Attempt to revoke user1's session using user2's credentials
        4. Verify 404 response (user2 cannot see user1's sessions)
    """
    short_id = uuid4().hex[:8]

    # Create user 1
    email1 = f"user1_{short_id}@test.com"
    password1 = "Str0ngP@ssw0rd!1"
    await client.post(
        "/api/v0/users/register",
        json={"username": email1, "email": email1, "password": password1, "full_name": "User 1"},
    )
    login1 = await client.post("/api/v0/auth/login", json={"username": email1, "password": password1})
    token1 = login1.json()["token"]["access_token"]
    headers1 = {"Authorization": f"Bearer {token1}"}

    # Get user1's session JTI
    sessions1 = await client.get("/api/v0/users/sessions", headers=headers1)
    jti1 = sessions1.json()["items"][0]["jti"]

    # Create user 2
    email2 = f"user2_{short_id}@test.com"
    password2 = "Str0ngP@ssw0rd!1"
    await client.post(
        "/api/v0/users/register",
        json={"username": email2, "email": email2, "password": password2, "full_name": "User 2"},
    )
    login2 = await client.post("/api/v0/auth/login", json={"username": email2, "password": password2})
    token2 = login2.json()["token"]["access_token"]
    headers2 = {"Authorization": f"Bearer {token2}"}

    # User 2 tries to revoke User 1's session
    response = await client.delete(f"/api/v0/users/sessions/{jti1}", headers=headers2)
    assert response.status_code == 404  # Session not found for user2


@pytest.mark.asyncio
async def test_revoke_invalid_jti_format(client: AsyncClient) -> None:
    """Test revoking with malformed JTI.

    Verifies that the endpoint handles invalid JTI formats gracefully.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register and login a user
        2. Attempt to revoke session with various invalid JTI formats
        3. Verify 404 response (session not found)
    """
    short_id = uuid4().hex[:8]
    email = f"invalid_jti_{short_id}@test.com"
    password = "Str0ngP@ssw0rd!1"
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Invalid JTI Test"},
    )
    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    token = login_response.json()["token"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Test with various invalid JTI formats
    # Note: Empty string causes redirect, so we skip it
    invalid_jtis = [
        "   ",  # Whitespace
        "invalid-jti-format",  # Invalid format
        "12345",  # Just numbers
    ]

    for invalid_jti in invalid_jtis:
        response = await client.delete(f"/api/v0/users/sessions/{invalid_jti}", headers=headers)
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_assign_role(client: AsyncClient) -> None:
    """Test assigning a role to a user.

    Verifies that a user with 'users:update' permission can assign a role to another user.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Create an admin user and a target user.
        2. Create a role with 'users:update' permission and assign to admin user.
        3. Create a target role.
        4. Login as admin user.
        5. Call assign role endpoint.
        6. Verify target user has the role.
    """
    # pylint: disable=too-many-locals
    db = DataBase()
    role_dao = RoleDAO(db)
    user_dao = UserDAO(db)

    short_id = uuid4().hex[:8]

    # 1. Create Admin User
    admin_email = f"admin_{short_id}@test.com"
    admin_password = "Str0ngP@ssw0rd!1"
    await client.post(
        "/api/v0/users/register",
        json={"username": admin_email, "email": admin_email, "password": admin_password, "full_name": "Admin User"},
    )
    admin_user = await user_dao.get_by_email(admin_email)
    assert admin_user is not None

    # 2. Create Target User
    target_email = f"target_{short_id}@test.com"
    await client.post(
        "/api/v0/users/register",
        json={
            "username": target_email,
            "email": target_email,
            "password": "Str0ngP@ssw0rd!1",
            "full_name": "Target User",
        },
    )
    target_user = await user_dao.get_by_email(target_email)
    assert target_user is not None

    # 3. Create 'users:update' permission if not exists
    # We assume it might exist or we insert it.
    await db.execute(
        "INSERT INTO permissions (name, description) VALUES ('users:update', 'Update users') ON CONFLICT DO NOTHING"
    )
    perms = await db.fetch("SELECT * FROM permissions WHERE name = 'users:update'", fetch_row=True)
    assert perms is not None
    perm_id = perms["id"]

    # 4. Create Admin Role with permission
    admin_role = await role_dao.create_role(
        RoleCreate(name=f"Admin_{short_id}", description="Admin Role", permission_ids=[perm_id])
    )

    # 5. Assign Admin Role to Admin User
    await user_dao.assign_roles(admin_user.id, [admin_role.id])

    # 6. Create Target Role
    target_role = await role_dao.create_role(RoleCreate(name=f"Target_{short_id}", description="Target Role"))

    # 7. Login as Admin
    login_response = await client.post("/api/v0/auth/login", json={"username": admin_email, "password": admin_password})
    assert login_response.status_code == 200
    token = login_response.json()["token"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 8. Call Assign Role Endpoint
    response = await client.post(
        f"/api/v0/users/{target_user.id}/roles", json={"role_ids": [str(target_role.id)]}, headers=headers
    )
    assert response.status_code == 204

    # 9. Verify
    updated_target_user = await user_dao.get_by_id(target_user.id)
    assert updated_target_user is not None
    role_ids = [r.id for r in updated_target_user.roles]
    assert target_role.id in role_ids


@pytest.mark.asyncio
async def test_token_version_increment(client: AsyncClient) -> None:
    """Test that token_version increments on critical updates.

    Verifies that token_version is incremented when:
    1. Password is updated.
    2. Roles are assigned.

    Args:
        client: AsyncClient fixture.
    """
    db = DataBase()
    user_dao = UserDAO(db)
    role_dao = RoleDAO(db)

    short_id = uuid4().hex[:8]
    email = f"token_ver_{short_id}@test.com"
    password = "Str0ngP@ssw0rd!1"

    # 1. Create User
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Token Version User"},
    )
    user = await user_dao.get_by_email(email)
    assert user is not None
    initial_version = user.token_version

    # 2. Update Password (via DAO for simplicity, or endpoint if we had one ready/accessible)
    # We'll use DAO to test the logic directly first, or we can use the endpoint if available.
    # The user didn't explicitly ask for a password update endpoint test, but the logic should be in DAO.
    # Let's check if we have a password update endpoint. We do have one from a previous task, but it requires sudo.
    # To avoid complexity of sudo token, let's test the DAO method directly if possible,
    # BUT wait, the user asked "when is the token version being updated?".
    # So I should ensure the DAO methods update it.

    # Test DAO update_password
    new_hash = "newhash123"
    await user_dao.update_password(user.id, new_hash)

    user_after_pw = await user_dao.get_by_id(user.id)
    assert user_after_pw is not None
    assert user_after_pw.token_version > initial_version
    pw_version = user_after_pw.token_version

    # 3. Assign Role
    role = await role_dao.create_role(RoleCreate(name=f"Role_{short_id}", description="Test Role"))
    await user_dao.assign_roles(user.id, [role.id])

    user_after_role = await user_dao.get_by_id(user.id)
    assert user_after_role is not None
    assert user_after_role.token_version > pw_version


@pytest.mark.asyncio
async def test_token_version_increment_on_role_update(client: AsyncClient) -> None:
    """Test that token_version increments when an assigned role is updated.

    Verifies that if a role's permissions are modified, all users with that role
    have their token_version incremented.

    Args:
        client: AsyncClient fixture.
    """
    db = DataBase()
    user_dao = UserDAO(db)
    role_dao = RoleDAO(db)

    short_id = uuid4().hex[:8]
    email = f"role_update_{short_id}@test.com"
    password = "Str0ngP@ssw0rd!1"

    # 1. Create User
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Role Update User"},
    )
    user = await user_dao.get_by_email(email)
    assert user is not None
    initial_version = user.token_version

    # 2. Create Role and Assign to User
    role = await role_dao.create_role(RoleCreate(name=f"Role_{short_id}", description="Test Role"))
    await user_dao.assign_roles(user.id, [role.id])

    # Get version after assignment (it should have incremented)
    user_after_assign = await user_dao.get_by_id(user.id)
    assert user_after_assign is not None
    assign_version = user_after_assign.token_version
    assert assign_version > initial_version

    # 3. Update Role (add permission)
    # First ensure a permission exists
    await db.execute(
        "INSERT INTO permissions (name, description) VALUES ('test:perm', 'Test Perm') ON CONFLICT DO NOTHING"
    )
    perms = await db.fetch("SELECT * FROM permissions WHERE name = 'test:perm'", fetch_row=True)
    assert perms is not None
    perm_id = perms["id"]

    await role_dao.update_role(role.id, RoleUpdate(permission_ids=[perm_id]))

    # 4. Verify User Token Version Incremented
    user_after_role_update = await user_dao.get_by_id(user.id)
    assert user_after_role_update is not None
    assert user_after_role_update.token_version > assign_version
