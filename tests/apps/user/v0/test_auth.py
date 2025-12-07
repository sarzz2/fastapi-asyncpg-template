from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from api.apps.user.v0.dao.role import RoleDAO
from api.apps.user.v0.dao.user import UserDAO
from api.apps.user.v0.service.auth import AuthService
from api.core.database import DataBase
from api.core.redis import RedisClient
from api.shared.redis_keys import RedisKeys


@pytest.mark.asyncio
async def test_auth_service_linking(client: AsyncClient) -> None:
    """Test that Google OAuth linking works for existing users with verified email."""
    short_id = uuid4().hex[:8]
    email = f"link_{short_id}@test.com"
    password = "strongpassword123"
    response = await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Original User"},
    )
    assert response.status_code == 201
    user_id = response.json()["id"]

    db = DataBase()
    user_dao = UserDAO(db)
    role_dao = RoleDAO(db)
    redis = RedisClient()
    auth_service = AuthService(user_dao, role_dao, redis.client)

    user_info = {"sub": f"google_{short_id}", "email": email, "email_verified": True, "name": "Google User"}

    linked_user = await auth_service.handle_google_oauth(user_info)

    assert linked_user.id == UUID(user_id)
    assert linked_user.email == email

    identities = await db.fetch("SELECT * FROM user_identities WHERE user_id = $1", linked_user.id)
    assert isinstance(identities, list)
    assert len(identities) == 1
    assert identities[0]["provider"] == "google"
    assert identities[0]["provider_user_id"] == f"google_{short_id}"


@pytest.mark.asyncio
async def test_update_password_standard_user(client: AsyncClient) -> None:
    """Test password update flow for standard users with sudo token."""
    short_id = uuid4().hex[:8]
    email = f"pwd_{short_id}@test.com"
    password = "oldpassword123"
    response = await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Password User"},
    )
    assert response.status_code == 201

    sudo_response = await client.post("/api/v0/auth/sudo", json={"username": email, "password": password})
    assert sudo_response.status_code == 200
    sudo_token = sudo_response.json()["sudo_token"]

    new_password = "newpassword123"
    headers = {"Authorization": f"Bearer {sudo_token}"}
    response = await client.post("/api/v0/auth/password", json={"password": new_password}, headers=headers)
    assert response.status_code == 204

    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": new_password})
    assert login_response.status_code == 200

    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    assert login_response.status_code == 401


@pytest.mark.asyncio
async def test_update_password_oauth_user(client: AsyncClient) -> None:
    """Test password update flow for OAuth users with sudo token."""
    short_id = uuid4().hex[:8]
    email = f"oauth_pwd_{short_id}@test.com"
    password = "initialpassword"
    response = await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "OAuth User"},
    )
    assert response.status_code == 201

    sudo_response = await client.post("/api/v0/auth/sudo", json={"username": email, "password": password})
    assert sudo_response.status_code == 200
    sudo_token = sudo_response.json()["sudo_token"]

    new_password = "setpassword123"
    headers = {"Authorization": f"Bearer {sudo_token}"}
    response = await client.post("/api/v0/auth/password", json={"password": new_password}, headers=headers)
    assert response.status_code == 204

    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": new_password})
    assert login_response.status_code == 200


@pytest.mark.asyncio
async def test_update_password_invalid_token(client: AsyncClient) -> None:
    """Test that password update fails with invalid token."""
    headers = {"Authorization": "Bearer invalid_token"}
    response = await client.post("/api/v0/auth/password", json={"password": "newpassword"}, headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_password_access_token_fails(client: AsyncClient) -> None:
    """Test that password update fails when using access token instead of sudo token."""
    short_id = uuid4().hex[:8]
    email = f"access_pwd_{short_id}@test.com"
    password = "password123"
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Access User"},
    )

    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    access_token = login_response.json()["token"]["access_token"]

    headers = {"Authorization": f"Bearer {access_token}"}
    response = await client.post("/api/v0/auth/password", json={"password": "newpassword"}, headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient) -> None:
    """Test token refresh flow returns new access and refresh tokens."""
    short_id = uuid4().hex[:8]
    email = f"refresh_{short_id}@test.com"
    password = "password123"
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Refresh User"},
    )
    login_response = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    assert login_response.status_code == 200
    refresh_token = login_response.json()["token"]["refresh_token"]

    response = await client.post("/api/v0/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    new_token = response.json()
    assert "access_token" in new_token["token"]
    assert "refresh_token" in new_token["token"]
    assert new_token["token"]["access_token"] != login_response.json()["token"]["access_token"]


@pytest.mark.asyncio
async def test_register_user_success(client: AsyncClient) -> None:
    """Test successful user registration."""
    short_id = uuid4().hex[:8]
    email = f"newuser_{short_id}@test.com"
    username = f"newuser_{short_id}"
    password = "SecurePassword123!"

    response = await client.post(
        "/api/v0/users/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "full_name": "New Test User",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == email
    assert data["username"] == username
    assert data["full_name"] == "New Test User"
    assert "id" in data
    assert "hashed_password" not in data

    # Verify user can login
    login_response = await client.post("/api/v0/auth/login", json={"username": username, "password": password})
    assert login_response.status_code == 200


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient) -> None:
    """Test that registering with duplicate username fails."""
    short_id = uuid4().hex[:8]
    username = f"duplicate_{short_id}"

    # First registration
    response1 = await client.post(
        "/api/v0/users/register",
        json={
            "username": username,
            "email": f"user1_{short_id}@test.com",
            "password": "password123",
            "full_name": "User One",
        },
    )
    assert response1.status_code == 201

    # Second registration with same username
    response2 = await client.post(
        "/api/v0/users/register",
        json={
            "username": username,
            "email": f"user2_{short_id}@test.com",
            "password": "password123",
            "full_name": "User Two",
        },
    )
    assert response2.status_code in [400, 409, 422]


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient) -> None:
    """Test that registering with duplicate email fails."""
    short_id = uuid4().hex[:8]
    email = f"duplicate_{short_id}@test.com"

    # First registration
    response1 = await client.post(
        "/api/v0/users/register",
        json={
            "username": f"user1_{short_id}",
            "email": email,
            "password": "password123",
            "full_name": "User One",
        },
    )
    assert response1.status_code == 201

    # Second registration with same email
    response2 = await client.post(
        "/api/v0/users/register",
        json={
            "username": f"user2_{short_id}",
            "email": email,
            "password": "password123",
            "full_name": "User Two",
        },
    )
    assert response2.status_code in [400, 409, 422]


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient) -> None:
    """Test that registration with invalid email format fails."""
    short_id = uuid4().hex[:8]
    invalid_emails = [
        "notanemail",
        "missing@domain",
        "@nodomain.com",
        "spaces in@email.com",
    ]

    for invalid_email in invalid_emails:
        response = await client.post(
            "/api/v0/users/register",
            json={
                "username": f"user_{short_id}_{invalid_email[:5]}",
                "email": invalid_email,
                "password": "password123",
                "full_name": "Test User",
            },
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_required_fields(client: AsyncClient) -> None:
    """Test that registration fails when required fields are missing."""
    short_id = uuid4().hex[:8]

    # Missing username
    response = await client.post(
        "/api/v0/users/register",
        json={
            "email": f"test_{short_id}@test.com",
            "password": "password123",
            "full_name": "Test User",
        },
    )
    assert response.status_code == 422

    # Missing email
    response = await client.post(
        "/api/v0/users/register",
        json={
            "username": f"user_{short_id}",
            "password": "password123",
            "full_name": "Test User",
        },
    )
    assert response.status_code == 422

    # Missing password
    response = await client.post(
        "/api/v0/users/register",
        json={
            "username": f"user_{short_id}",
            "email": f"test_{short_id}@test.com",
            "full_name": "Test User",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_google_login_redirect(client: AsyncClient) -> None:
    """Test Google OAuth login redirect."""
    response = await client.get("/api/v0/auth/google/login", follow_redirects=False)

    assert response.status_code == 307
    assert "location" in response.headers
    redirect_url = response.headers["location"]
    assert "accounts.google.com" in redirect_url
    assert "client_id" in redirect_url
    assert "state" in redirect_url
    assert "redirect_uri" in redirect_url


@pytest.mark.asyncio
async def test_google_callback_missing_code(client: AsyncClient) -> None:
    """Test Google callback fails without authorization code."""
    response = await client.get("/api/v0/auth/google/callback?state=somestate")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_missing_state(client: AsyncClient) -> None:
    """Test Google callback fails without state parameter."""
    response = await client.get("/api/v0/auth/google/callback?code=somecode")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_invalid_state(client: AsyncClient) -> None:
    """Test Google callback fails with invalid/expired state."""
    response = await client.get("/api/v0/auth/google/callback?code=somecode&state=invalid_state_12345")
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower() or "expired" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_google_callback_success(client: AsyncClient) -> None:
    """Test successful Google OAuth callback."""
    state_key = RedisKeys.OAUTH_STATE_GOOGLE.format(state="valid_state")
    redis = RedisClient()
    await redis.client.set(state_key, "1", ex=300)

    # Mock httpx used inside the route
    with patch("api.apps.user.v0.routes.auth.httpx.AsyncClient") as MockClientClass:
        mock_internal_client = MagicMock()
        mock_internal_client.post = AsyncMock(
            return_value=MagicMock(status_code=200, json=lambda: {"access_token": "google_access_token"})
        )
        mock_internal_client.get = AsyncMock(
            return_value=MagicMock(
                status_code=200,
                json=lambda: {
                    "sub": "google_123",
                    "email": "test@google.com",
                    "email_verified": True,
                    "name": "Google Test User",
                },
            )
        )

        # Configure the context manager to return our mock client
        MockClientClass.return_value.__aenter__.return_value = mock_internal_client
        MockClientClass.return_value.__aexit__.return_value = None

        response = await client.get("/api/v0/auth/google/callback?code=valid_code&state=valid_state")

        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "user" in data
        assert data["user"]["email"] == "test@google.com"


@pytest.mark.asyncio
async def test_google_sudo_token_invalid(client: AsyncClient) -> None:
    """Test Google sudo token creation with invalid token."""
    # Mock verify_token to raise exception
    with patch.object(AuthService, "verify_access_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.side_effect = Exception("Invalid token")

        response = await client.post("/api/v0/auth/google/sudo", json={"access_token": "invalid_token"})

        assert response.status_code == 401
