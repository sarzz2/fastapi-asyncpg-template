# pylint: disable=duplicate-code  # Shared user-registration pattern across test modules is intentional
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


async def register_test_user(client: AsyncClient, prefix: str = "auth") -> tuple[str, str]:
    """
    Helper to register a users and return (email, password).
    """
    short_id = uuid4().hex[:8]
    email = f"{prefix}_{short_id}@example.com"
    password = "Str0ngP@ssw0rd!123"
    await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": password, "full_name": "Auth Test User"},
    )
    return email, password


@pytest.mark.asyncio
async def test_auth_service_linking(client: AsyncClient) -> None:
    """
    Verify that Google OAuth correctly links to an existing user with a verified email.
    """
    short_id = uuid4().hex[:8]
    email = f"link_{short_id}@test.com"

    # 1. Register base user
    reg_resp = await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": email, "password": "OriginalPassword1!", "full_name": "Original User"},
    )
    assert reg_resp.status_code == 201
    user_id = reg_resp.json()["id"]

    db = DataBase()
    redis = RedisClient()
    try:
        auth_service = AuthService(UserDAO(db), RoleDAO(db), redis.client)
        user_info = {"sub": f"google_{short_id}", "email": email, "email_verified": True, "name": "Google User"}

        linked_user = await auth_service.handle_google_oauth(user_info)

        assert linked_user.id == UUID(user_id)

        # Verify identity persistence
        identities = await db.fetch("SELECT * FROM user_identities WHERE user_id = $1", linked_user.id)
        assert identities is not None
        assert len(identities) == 1
        assert identities[0]["provider"] == "google"
        assert identities[0]["provider_user_id"] == f"google_{short_id}"
    finally:
        await redis.close()
        await db.close_pool()


@pytest.mark.asyncio
async def test_update_password_with_sudo_token(client: AsyncClient) -> None:
    """
    Verify the full password update flow requiring a sudo token.
    """
    email, old_password = await register_test_user(client, "pwd")

    # 1. Obtain sudo token
    sudo_resp = await client.post("/api/v0/auth/sudo", json={"username": email, "password": old_password})
    assert sudo_resp.status_code == 200
    sudo_token = sudo_resp.json()["sudo_token"]

    # 2. Update password
    new_password = "NewStr0ngP@ssw0rd!1"
    headers = {"Authorization": f"Bearer {sudo_token}"}
    update_resp = await client.post("/api/v0/auth/password", json={"password": new_password}, headers=headers)
    assert update_resp.status_code == 204

    # 3. Verify login with new password
    login_resp = await client.post("/api/v0/auth/login", json={"username": email, "password": new_password})
    assert login_resp.status_code == 200

    # 4. Verify old password no longer works
    fail_resp = await client.post("/api/v0/auth/login", json={"username": email, "password": old_password})
    assert fail_resp.status_code == 401


@pytest.mark.asyncio
async def test_update_password_requires_sudo_token(client: AsyncClient) -> None:
    """
    Verify that sensitive password updates reject standard access tokens.
    """
    email, password = await register_test_user(client, "pwd_fail")

    login_resp = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    access_token = login_resp.json()["token"]["access_token"]

    # Attempt update with access token (expect failure)
    headers = {"Authorization": f"Bearer {access_token}"}
    response = await client.post("/api/v0/auth/password", json={"password": "NewSecret1!"}, headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_refresh_lifecycle(client: AsyncClient) -> None:
    """
    Verify that a valid refresh token can be used to rotate both access and refresh tokens.
    """
    email, password = await register_test_user(client, "refresh")

    login_resp = await client.post("/api/v0/auth/login", json={"username": email, "password": password})
    initial_tokens = login_resp.json()["token"]
    refresh_token = initial_tokens["refresh_token"]

    response = await client.post("/api/v0/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200

    new_tokens = response.json()["token"]
    assert new_tokens["access_token"] != initial_tokens["access_token"]
    assert new_tokens["refresh_token"] != initial_tokens["refresh_token"]


@pytest.mark.asyncio
async def test_user_registration_and_login_flow(client: AsyncClient) -> None:
    """
    Verify successful end-to-end registration and subsequent login.
    """
    short_id = uuid4().hex[:8]
    payload = {
        "username": f"user_{short_id}",
        "email": f"reg_{short_id}@example.com",
        "password": "Password123!",
        "full_name": "Full Name",
    }

    reg_resp = await client.post("/api/v0/users/register", json=payload)
    assert reg_resp.status_code == 201

    login_resp = await client.post(
        "/api/v0/auth/login", json={"username": payload["username"], "password": payload["password"]}
    )
    assert login_resp.status_code == 200


@pytest.mark.asyncio
async def test_registration_validation_duplicates(client: AsyncClient) -> None:
    """
    Verify that registration fails for duplicate emails or usernames.
    """
    email, password = await register_test_user(client, "dup")

    # Duplicate Email
    resp = await client.post(
        "/api/v0/users/register",
        json={"username": f"other_{uuid4().hex[:4]}", "email": email, "password": password, "full_name": "X"},
    )
    assert resp.status_code in [400, 409, 422]

    # Duplicate Username (should fail even with unique email)
    resp = await client.post(
        "/api/v0/users/register",
        json={"username": email, "email": f"other_{uuid4().hex[:4]}@test.com", "password": password, "full_name": "X"},
    )
    assert resp.status_code in [400, 409, 422]


@pytest.mark.asyncio
async def test_registration_validation_format(client: AsyncClient) -> None:
    """
    Verify that registration rejects invalid email formats.
    """
    invalid_emails = ["not_an_email", "missing@domain", "@only_domain.com"]

    for email in invalid_emails:
        resp = await client.post(
            "/api/v0/users/register",
            json={"username": f"u_{uuid4().hex[:4]}", "email": email, "password": "P", "full_name": "F"},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_google_oauth_redirect_generation(client: AsyncClient) -> None:
    """
    Verify that the Google login endpoint generates a proper redirect URL.
    """
    response = await client.get("/api/v0/auth/google/login", follow_redirects=False)

    assert response.status_code == 307
    location = response.headers["location"]
    assert "accounts.google.com" in location
    assert "client_id" in location
    assert "state" in location


@pytest.mark.asyncio
async def test_google_callback_validation(client: AsyncClient) -> None:
    """
    Verify that the Google callback requires both code and valid state.
    """
    # Missing code
    assert (await client.get("/api/v0/auth/google/callback?state=s")).status_code == 400
    # Missing state
    assert (await client.get("/api/v0/auth/google/callback?code=c")).status_code == 400
    # Invalid state
    assert (await client.get("/api/v0/auth/google/callback?code=c&state=invalid")).status_code == 400


@pytest.mark.asyncio
async def test_google_callback_authentication_success(client: AsyncClient) -> None:
    """
    Verify successful authentication via Google OAuth callback with mocked external API.
    """
    state = "valid_oauth_state"
    state_key = RedisKeys.OAUTH_STATE_GOOGLE.format(state=state)
    redis = RedisClient()

    try:
        await redis.client.set(state_key, "1", ex=300)

        with patch("api.apps.user.v0.routes.auth.httpx.AsyncClient") as MockClientClass:
            mock_client = MagicMock()
            # Mock Token Exchange
            mock_client.post = AsyncMock(
                return_value=MagicMock(status_code=200, json=lambda: {"access_token": "g_access"})
            )
            # Mock User Info
            mock_client.get = AsyncMock(
                return_value=MagicMock(
                    status_code=200,
                    json=lambda: {
                        "sub": "g_123",
                        "email": "oauth_success@test.com",
                        "email_verified": True,
                        "name": "OAuth Success User",
                    },
                )
            )
            MockClientClass.return_value.__aenter__.return_value = mock_client

            response = await client.get(f"/api/v0/auth/google/callback?code=valid&state={state}")
            assert response.status_code == 200
            assert "token" in response.json()
            assert response.json()["user"]["email"] == "oauth_success@test.com"

    finally:
        await redis.close()


@pytest.mark.asyncio
async def test_google_sudo_token_rejection(client: AsyncClient) -> None:
    """
    Verify rejection of invalid external tokens for sudo elevation.
    """
    with patch.object(AuthService, "verify_access_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.side_effect = Exception("Mocked Invalid Token")

        response = await client.post("/api/v0/auth/google/sudo", json={"access_token": "bad_token"})
        assert response.status_code == 401
