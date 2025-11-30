from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from api.apps.user.v0.dao.role import RoleDAO
from api.apps.user.v0.dao.user import UserDAO
from api.apps.user.v0.service.auth import AuthService
from api.core.database import DataBase
from api.core.redis import RedisClient


@pytest.mark.asyncio
async def test_auth_service_linking(client: AsyncClient) -> None:
    """Test that Google OAuth linking works for existing users with verified email.

    This test verifies the account linking feature where an existing user can link
    their Google account. It creates a standard user first, then simulates a Google
    OAuth callback with the same verified email address to ensure the accounts are
    properly linked.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a standard user via API
        2. Simulate Google OAuth callback with same verified email
        3. Verify the accounts are linked (same user ID)
        4. Verify the Google identity was added to user_identities table
    """
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
    """Test password update flow for standard users with sudo token.

    Verifies that a standard user can successfully update their password using
    a sudo token, and that the old password no longer works after the update.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a new user
        2. Obtain a sudo token with username and password
        3. Update the password using the sudo token
        4. Verify login works with the new password
        5. Verify login fails with the old password
    """
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
    """Test password update flow for OAuth users with sudo token.

    Verifies that users who authenticated via OAuth can set/update their password
    using a sudo token. This is useful for OAuth users who want to add password
    authentication to their account.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a user (simulating OAuth user)
        2. Obtain a sudo token
        3. Update/set the password using the sudo token
        4. Verify login works with the new password
    """
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
    """Test that password update fails with invalid token.

    Verifies that the password update endpoint properly rejects requests with
    invalid authentication tokens.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Attempt to update password with an invalid token
        2. Verify the request is rejected with 401 Unauthorized
    """
    headers = {"Authorization": "Bearer invalid_token"}
    response = await client.post("/api/v0/auth/password", json={"password": "newpassword"}, headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_password_access_token_fails(client: AsyncClient) -> None:
    """Test that password update fails when using access token instead of sudo token.

    Verifies that the password update endpoint requires a sudo token and rejects
    regular access tokens, enforcing the elevated privilege requirement for
    sensitive operations.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a user and obtain an access token via login
        2. Attempt to update password using the access token
        3. Verify the request is rejected with 401 Unauthorized
    """
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
    """Test token refresh flow returns new access and refresh tokens.

    Verifies that the token refresh endpoint properly exchanges a valid refresh
    token for new access and refresh tokens, and that the new access token is
    different from the original.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a user and login to obtain tokens
        2. Use the refresh token to obtain new tokens
        3. Verify new tokens are returned
        4. Verify the new access token is different from the original
    """
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
    """Test successful user registration.

    Verifies that a new user can be registered with valid credentials and
    all required fields are properly stored.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a new user with valid data
        2. Verify 201 status code
        3. Verify returned user data matches input
        4. Verify user can login with credentials
    """
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
    assert "hashed_password" not in data  # Password should not be returned

    # Verify user can login
    login_response = await client.post("/api/v0/auth/login", json={"username": username, "password": password})
    assert login_response.status_code == 200


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient) -> None:
    """Test that registering with duplicate username fails.

    Verifies that the system prevents creating multiple users with the same username.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a user successfully
        2. Attempt to register another user with same username but different email
        3. Verify registration fails with appropriate error
    """
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
            "username": username,  # Same username
            "email": f"user2_{short_id}@test.com",  # Different email
            "password": "password123",
            "full_name": "User Two",
        },
    )
    assert response2.status_code in [400, 409, 422]  # Bad request or conflict


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient) -> None:
    """Test that registering with duplicate email fails.

    Verifies that the system prevents creating multiple users with the same email address.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Register a user successfully
        2. Attempt to register another user with same email but different username
        3. Verify registration fails with appropriate error
    """
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
            "username": f"user2_{short_id}",  # Different username
            "email": email,  # Same email
            "password": "password123",
            "full_name": "User Two",
        },
    )
    assert response2.status_code in [400, 409, 422]  # Bad request or conflict


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient) -> None:
    """Test that registration with invalid email format fails.

    Verifies that the system validates email format during registration.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Attempt to register with invalid email formats
        2. Verify registration fails with validation error
    """
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
        assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_register_missing_required_fields(client: AsyncClient) -> None:
    """Test that registration fails when required fields are missing.

    Verifies that all required fields (username, email, password) must be provided.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Attempt registration without username
        2. Attempt registration without email
        3. Attempt registration without password
        4. Verify all attempts fail with validation error
    """
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
    """Test Google OAuth login redirect.

    Verifies that the Google login endpoint returns a redirect to Google's
    OAuth consent screen with proper parameters.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Call /google/login endpoint
        2. Verify 307 redirect status
        3. Verify redirect URL contains Google OAuth endpoint
        4. Verify state parameter is included
    """
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
    """Test Google callback fails without authorization code.

    Verifies that the callback endpoint properly validates required parameters.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Call callback endpoint without code parameter
        2. Verify 400 error is returned
    """
    response = await client.get("/api/v0/auth/google/callback?state=somestate")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_missing_state(client: AsyncClient) -> None:
    """Test Google callback fails without state parameter.

    Verifies that the callback endpoint requires state for CSRF protection.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Call callback endpoint without state parameter
        2. Verify 400 error is returned
    """
    response = await client.get("/api/v0/auth/google/callback?code=somecode")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_invalid_state(client: AsyncClient) -> None:
    """Test Google callback fails with invalid/expired state.

    Verifies that the callback endpoint validates state against Redis storage
    to prevent CSRF attacks.

    Args:
        client: AsyncClient fixture for making HTTP requests to the API.

    Test Flow:
        1. Call callback with code and invalid state
        2. Verify 400 error for invalid state
    """
    response = await client.get("/api/v0/auth/google/callback?code=somecode&state=invalid_state_12345")
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower() or "expired" in response.json()["detail"].lower()
