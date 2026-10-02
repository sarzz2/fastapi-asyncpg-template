import json
from uuid import uuid4

import pyotp
import pytest
from httpx import AsyncClient

from api.core.redis import redis_client
from api.shared.redis_keys import RedisKeys


async def register_and_login_user(client: AsyncClient, prefix: str = "2fa") -> tuple[str, str, dict[str, str]]:
    """
    Helper to register a user, login, and return (username, password, auth_headers).
    """
    user_email = f"{prefix}_{uuid4().hex[:8]}@example.com"
    user_pass = "Str0ngP@ssw0rd!123"
    await client.post(
        "/api/v0/users/register",
        json={"username": user_email, "email": user_email, "password": user_pass, "full_name": "Test User"},
    )
    login_data = (await client.post("/api/v0/auth/login", json={"username": user_email, "password": user_pass})).json()
    return user_email, user_pass, {"Authorization": f"Bearer {login_data['token']['access_token']}"}


async def get_sudo_headers(client: AsyncClient, username: str, password: str) -> dict[str, str]:
    """
    Helper to obtain sudo token and return sudo authorization headers.
    """
    resp = await client.post(
        "/api/v0/auth/sudo",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    sudo_token = resp.json()["sudo_token"]
    return {"Authorization": f"Bearer {sudo_token}"}


async def enable_2fa_for_user(client: AsyncClient, headers: dict[str, str]) -> tuple[str, list[str]]:
    """
    Helper to setup and confirm 2FA, returning (secret, backup_codes).
    """
    resp = await client.post("/api/v0/auth/2fa/setup", headers=headers)
    secret = resp.json()["secret"]
    resp = await client.post(
        "/api/v0/auth/2fa/confirm",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    return secret, resp.json()["backup_codes"]


@pytest.mark.asyncio
async def test_two_factor_status_default(client: AsyncClient) -> None:
    """
    Verify that 2FA is disabled by default on new accounts.
    """
    _, _, headers = await register_and_login_user(client, prefix="status_default")

    resp = await client.get("/api/v0/auth/2fa", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_enabled"] is False
    assert data["backup_codes_remaining"] == 0


@pytest.mark.asyncio
async def test_two_factor_setup_and_confirm_flow(client: AsyncClient) -> None:
    """
    Verify complete 2FA setup, validation of OTP, and activation with backup codes.
    """
    _, _, headers = await register_and_login_user(client, prefix="setup_confirm")

    # 1. Initiate setup
    setup_resp = await client.post("/api/v0/auth/2fa/setup", headers=headers)
    assert setup_resp.status_code == 200
    setup_data = setup_resp.json()
    assert "secret" in setup_data
    assert "qr_code" in setup_data
    assert setup_data["qr_code"].startswith("data:image/svg+xml")
    assert "otpauth_url" in setup_data

    secret = setup_data["secret"]

    # 2. Reject invalid code
    bad_confirm = await client.post(
        "/api/v0/auth/2fa/confirm",
        headers=headers,
        json={"code": "000000"},
    )
    assert bad_confirm.status_code == 400

    # 3. Confirm with valid code
    totp = pyotp.TOTP(secret)
    valid_code = totp.now()

    confirm_resp = await client.post(
        "/api/v0/auth/2fa/confirm",
        headers=headers,
        json={"code": valid_code},
    )
    assert confirm_resp.status_code == 200
    confirm_data = confirm_resp.json()
    assert confirm_data["status"] == "enabled"
    assert len(confirm_data["backup_codes"]) == 10

    # 4. Check status shows active with 10 backup codes
    status_resp = await client.get("/api/v0/auth/2fa", headers=headers)
    assert status_resp.status_code == 200
    assert status_resp.json()["is_enabled"] is True
    assert status_resp.json()["backup_codes_remaining"] == 10


@pytest.mark.asyncio
async def test_login_flow_with_two_factor_challenge(client: AsyncClient) -> None:
    """
    Verify that login triggers a 2FA challenge when enabled, and challenge verification succeeds.
    """
    username, password, headers = await register_and_login_user(client, prefix="login_challenge")

    # Enable 2FA
    setup_resp = await client.post("/api/v0/auth/2fa/setup", headers=headers)
    secret = setup_resp.json()["secret"]
    valid_code = pyotp.TOTP(secret).now()
    await client.post("/api/v0/auth/2fa/confirm", headers=headers, json={"code": valid_code})

    # Log in again with credentials
    login_resp = await client.post(
        "/api/v0/auth/login",
        json={"username": username, "password": password},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data.get("requires_2fa") is True
    assert "two_factor_token" in login_data
    challenge_token = login_data["two_factor_token"]

    # Verify invalid challenge code fails
    bad_verify = await client.post(
        "/api/v0/auth/2fa/verify",
        json={"two_factor_token": challenge_token, "code": "999999"},
    )
    assert bad_verify.status_code == 400

    # Verify valid challenge code succeeds
    fresh_code = pyotp.TOTP(secret).now()
    verify_resp = await client.post(
        "/api/v0/auth/2fa/verify",
        json={"two_factor_token": challenge_token, "code": fresh_code},
    )
    assert verify_resp.status_code == 200
    verify_data = verify_resp.json()
    assert "token" in verify_data
    assert "access_token" in verify_data["token"]
    assert "refresh_token" in verify_data["token"]
    assert verify_data["user"]["username"] == username


@pytest.mark.asyncio
async def test_login_with_backup_recovery_code(client: AsyncClient) -> None:
    """
    Verify login using a single-use backup recovery code and verify it cannot be reused.
    """
    username, password, headers = await register_and_login_user(client, prefix="backup_recovery")
    _, backup_codes = await enable_2fa_for_user(client, headers)
    first_code = backup_codes[0]

    # Login and challenge
    resp = await client.post(
        "/api/v0/auth/login",
        json={"username": username, "password": password},
    )
    challenge_token = resp.json()["two_factor_token"]

    # Verify using backup recovery code
    resp = await client.post(
        "/api/v0/auth/2fa/verify",
        json={"two_factor_token": challenge_token, "code": first_code},
    )
    assert resp.status_code == 200
    new_headers = {"Authorization": f"Bearer {resp.json()['token']['access_token']}"}

    # Verify backup code count decreased to 9
    resp = await client.get("/api/v0/auth/2fa", headers=new_headers)
    assert resp.json()["backup_codes_remaining"] == 9

    # Second login: Attempting to reuse the exact same backup code must fail
    resp = await client.post(
        "/api/v0/auth/login",
        json={"username": username, "password": password},
    )
    challenge_token2 = resp.json()["two_factor_token"]

    resp = await client.post(
        "/api/v0/auth/2fa/verify",
        json={"two_factor_token": challenge_token2, "code": first_code},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_disable_two_factor_with_sudo(client: AsyncClient) -> None:
    """
    Verify that disabling 2FA requires sudo privilege and reverts login to standard flow.
    """
    username, password, headers = await register_and_login_user(client, prefix="disable_sudo")
    secret, _ = await enable_2fa_for_user(client, headers)

    # Disabling without sudo token should fail
    resp = await client.post(
        "/api/v0/auth/2fa/disable",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code in (401, 403)

    # Disabling with invalid code should fail even with sudo
    sudo_headers = await get_sudo_headers(client, username, password)
    resp = await client.post(
        "/api/v0/auth/2fa/disable",
        headers=sudo_headers,
        json={"code": "000000"},
    )
    assert resp.status_code == 400

    # Obtain sudo token and disable with valid code
    resp = await client.post(
        "/api/v0/auth/2fa/disable",
        headers=sudo_headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code == 204

    # Check status
    resp = await client.get("/api/v0/auth/2fa", headers=headers)
    assert resp.json()["is_enabled"] is False

    # Next login should not require 2FA
    resp = await client.post(
        "/api/v0/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    assert "token" in resp.json()
    assert "access_token" in resp.json()["token"]


@pytest.mark.asyncio
async def test_regenerate_backup_codes(client: AsyncClient) -> None:
    """
    Verify regenerating backup codes requires sudo privilege and invalidates previous codes.
    """
    username, password, headers = await register_and_login_user(client, prefix="regen_codes")
    secret, original_codes = await enable_2fa_for_user(client, headers)

    # Regenerating without sudo token fails
    resp = await client.post(
        "/api/v0/auth/2fa/backup-codes",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code in (401, 403)

    # Regenerate with sudo token and valid code
    sudo_headers = await get_sudo_headers(client, username, password)
    resp = await client.post(
        "/api/v0/auth/2fa/backup-codes",
        headers=sudo_headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code == 200
    new_codes = resp.json()
    assert len(new_codes) == 10
    assert new_codes != original_codes

    # Old backup code must fail
    resp = await client.post(
        "/api/v0/auth/login",
        json={"username": username, "password": password},
    )
    challenge_token = resp.json()["two_factor_token"]
    resp = await client.post(
        "/api/v0/auth/2fa/verify",
        json={"two_factor_token": challenge_token, "code": original_codes[0]},
    )
    assert resp.status_code == 400

    # New backup code succeeds
    resp = await client.post(
        "/api/v0/auth/2fa/verify",
        json={"two_factor_token": challenge_token, "code": new_codes[0]},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_refresh_token_enforces_mfa(client: AsyncClient) -> None:
    """
    Verify that token refresh blocks users when MFA is enforced by system policy
    until the user configures two-factor authentication.
    """
    user_email = f"mfa_refresh_{uuid4().hex[:8]}@example.com"
    user_pass = "Str0ngP@ssw0rd!123"
    await client.post(
        "/api/v0/users/register",
        json={"username": user_email, "email": user_email, "password": user_pass, "full_name": "Test User"},
    )
    login_data = (await client.post("/api/v0/auth/login", json={"username": user_email, "password": user_pass})).json()
    refresh_token = login_data["token"]["refresh_token"]

    # When MFA is NOT enforced, refresh succeeds
    resp = await client.post("/api/v0/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    new_refresh_token = resp.json()["token"]["refresh_token"]

    # Enforce MFA in system configuration
    await redis_client.client.set(
        RedisKeys.SYSTEM_CONFIG_CACHE,
        json.dumps({"id": 1, "enforce_mfa": True, "updated_at": "2026-01-01T00:00:00Z"}),
    )

    try:
        # Refresh without 2FA enabled should fail with 428 Precondition Required
        resp = await client.post("/api/v0/auth/refresh", json={"refresh_token": new_refresh_token})
        assert resp.status_code == 428
        assert "MFA enrollment is required by system policy" in resp.json()["detail"]
    finally:
        # Revert system config cache
        await redis_client.client.delete(RedisKeys.SYSTEM_CONFIG_CACHE)
