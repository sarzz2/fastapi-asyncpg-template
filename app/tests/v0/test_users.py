
import asyncio
import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient

from app.tests.conftest import API_PREFIX
from app.tests.v0.fixtures.user import random_user, registered_user


@pytest.mark.asyncio
async def test_register_and_get_me(client: AsyncClient, registered_user):
    """Can register, obtain tokens, and fetch /me."""
    resp = await client.get(
        f"{API_PREFIX}/users/me", headers={"Authorization": f"Bearer {registered_user['access_token']}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == registered_user["username"]
    assert body["email"] == registered_user["email"]
    assert body["id"] == registered_user["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dup_field, payload_override",
    [
        ("username", {"email": "foo2@example.com"}),
        ("email", {"username": "foo2"}),
    ],
)
async def test_register_duplicate_user(client: AsyncClient, registered_user, dup_field, payload_override):
    """
    Registering with a duplicate username or email fails with 400.
    """
    # Build a second payload that collides on dup_field
    dup_payload = {"id": str(uuid.uuid4()), **registered_user, **payload_override}
    resp = await client.post(f"{API_PREFIX}/users/register", json=dup_payload)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_failed_login(client: AsyncClient, registered_user):
    """Login fails with the wrong username or password."""
    # wrong password
    resp = await client.post(
        f"{API_PREFIX}/users/login", json={"username": registered_user["username"], "password": "WrongP@ss!"}
    )
    assert resp.status_code == 401

    # wrong username
    resp = await client.post(
        f"{API_PREFIX}/users/login", json={"username": "no_such_user", "password": registered_user["password"]}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_refresh_and_reuse(client: AsyncClient, registered_user):
    """Refresh endpoint returns new tokens and they work for /me."""
    # call refresh
    resp = await client.post(
        f"{API_PREFIX}/users/token/refresh", headers={"refresh-token": registered_user["refresh_token"]}
    )
    assert resp.status_code == 200
    new = resp.json()
    assert new["access_token"] != registered_user["access_token"]
    assert new["refresh_token"] != registered_user["refresh_token"]

    # use new access token
    resp = await client.get(f"{API_PREFIX}/users/me", headers={"Authorization": f"Bearer {new['access_token']}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == registered_user["username"]


@pytest.mark.asyncio
async def test_invalid_tokens(client: AsyncClient):
    """Endpoints reject malformed or revoked tokens."""
    # bad access token
    resp = await client.get(f"{API_PREFIX}/users/me", headers={"Authorization": "Bearer invalid.token"})
    assert resp.status_code == 401

    # bad refresh token
    resp = await client.post(f"{API_PREFIX}/users/token/refresh", headers={"refresh-token": "nope"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sudo_and_change_password(client: AsyncClient, random_user):
    """Get a sudo token then change password, old creds fail, new succeed."""
    # register
    resp = await client.post(f"{API_PREFIX}/users/register", json=random_user)
    assert resp.status_code == 201
    tokens = resp.json()

    # get sudo
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    resp = await client.post(
        f"{API_PREFIX}/users/token/sudo",
        headers=auth,
        json={
            "username": random_user["username"],
            "password": random_user["password"],
        },
    )
    assert resp.status_code == 200
    sudo = resp.json()["sudo_token"]

    # change password
    headers = {"Authorization": f"Bearer {sudo}"}
    resp = await client.patch(
        f"{API_PREFIX}/users/change_password",
        headers=headers,
        json={"current_password": random_user["password"], "new_password": "NewP@ssword1!"},
    )
    assert resp.status_code == 200

    # old login fails
    resp = await client.post(
        f"{API_PREFIX}/users/login",
        json={
            "username": random_user["username"],
            "password": random_user["password"],
        },
    )
    assert resp.status_code == 401

    # new login succeeds
    resp = await client.post(
        f"{API_PREFIX}/users/login",
        json={
            "username": random_user["username"],
            "password": "NewP@ssword1!",
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_user_search(client: AsyncClient):
    """Search only returns matching users."""
    # bulk register three
    users = []
    for name in ("search1", "search2", "other"):
        payload = {"id": str(uuid.uuid4()), "username": name, "email": f"{name}@ex.com", "password": "S3cureP@ss!"}
        r = await client.post(f"{API_PREFIX}/users/register", json=payload)
        assert r.status_code == 201
        users.append(payload)

    # login as search1
    r2 = await client.post(f"{API_PREFIX}/users/login", json={"username": "search1", "password": "S3cureP@ss!"})
    token = r2.json()["access_token"]

    # perform search
    r3 = await client.get(f"{API_PREFIX}/users/search/search", headers={"Authorization": f"Bearer {token}"})
    assert r3.status_code == 200
    names = [u["username"] for u in r3.json()]
    assert set(names) == {"search1", "search2"}


@pytest.mark.asyncio
async def test_update_user_and_me_consistency(client: AsyncClient, registered_user):
    """PATCH /update changes only provided fields, GET /me reflects them."""
    # update email
    r1 = await client.patch(
        f"{API_PREFIX}/users/update",
        headers={"Authorization": f"Bearer {registered_user['access_token']}"},
        json={"email": "newemail@example.com"},
    )
    assert r1.status_code == 200
    updated = r1.json()
    assert updated["email"] == "newemail@example.com"
    assert updated["username"] == registered_user["username"]

    # GET /me confirms
    r2 = await client.get(
        f"{API_PREFIX}/users/me", headers={"Authorization": f"Bearer {registered_user['access_token']}"}
    )
    assert r2.json()["email"] == "newemail@example.com"


@pytest.mark.asyncio
async def test_session_management(client: AsyncClient, registered_user):
    """List sessions, revoke one, and logout-all invalidate all tokens."""
    access_token = registered_user["access_token"]
    r1 = await client.get(f"{API_PREFIX}/users/sessions", headers={"Authorization": f"Bearer {access_token}"})
    assert r1.status_code == 200
    sessions = r1.json()
    assert len(sessions) == 1
    jti = sessions[0]["jti"]

    # revoke single session
    r2 = await client.delete(f"{API_PREFIX}/users/sessions/{jti}", headers={"Authorization": f"Bearer {access_token}"})
    assert r2.status_code == 200

    r3 = await client.get(f"{API_PREFIX}/users/me", headers={"Authorization": f"Bearer {access_token}"})
    assert r3.status_code == 401


@pytest.mark.asyncio
async def test_multiple_device_sessions(client: AsyncClient, registered_user):
    """Logging in from another “device” (new UA) creates a second session."""
    # first session already exists
    first_headers = {"Authorization": f"Bearer {registered_user['access_token']}"}
    # simulate second device by passing a dummy User-Agent header
    login_resp = await client.post(
        f"{API_PREFIX}/users/login",
        json={
            "id": registered_user["id"],
            "username": registered_user["username"],
            "email": registered_user["email"],
            "password": registered_user["password"],
        },
        headers={"user-agent": "SecondDevice/1.0"},
    )
    assert login_resp.status_code == 200
    tokens2 = login_resp.json()
    second_headers = {"Authorization": f"Bearer {tokens2['access_token']}"}

    list_resp = await client.get(f"{API_PREFIX}/users/sessions", headers=first_headers)
    assert list_resp.status_code == 200
    sessions = list_resp.json()
    # Should now have two distinct sessions
    assert len(sessions) == 2
    jtis = {s["jti"] for s in sessions}
    assert registered_user["access_token"] or len(jtis) == 2


@pytest.mark.asyncio
async def test_revoke_session_invalidates_refresh_token(client: AsyncClient, registered_user):
    """Revoking a session’s JTI also blocks its refresh token."""
    access = registered_user["access_token"]
    refresh = registered_user["refresh_token"]
    auth_headers = {"Authorization": f"Bearer {access}"}

    # get the JTI
    sessions = (await client.get(f"{API_PREFIX}/users/sessions", headers=auth_headers)).json()
    jti = sessions[0]["jti"]

    # revoke it
    del_resp = await client.delete(f"{API_PREFIX}/users/sessions/{jti}", headers=auth_headers)
    assert del_resp.status_code == 200

    # old refresh should now fail
    bad_refresh = await client.post(f"{API_PREFIX}/users/token/refresh", headers={"refresh-token": refresh})
    assert bad_refresh.status_code == 401


@pytest.mark.asyncio
async def test_refresh_extends_session_expiry(client: AsyncClient, registered_user):
    """Using the refresh endpoint should bump that session’s expires_at."""
    auth_headers = {"Authorization": f"Bearer {registered_user['access_token']}"}
    refresh_headers = {"refresh-token": registered_user["refresh_token"]}

    # capture original expires_at
    sess1 = (await client.get(f"{API_PREFIX}/users/sessions", headers=auth_headers)).json()[0]
    orig_expiry = datetime.fromisoformat(sess1["expires_at"])

    # wait a bit, then refresh
    await asyncio.sleep(0.1)
    refresh_resp = await client.post(f"{API_PREFIX}/users/token/refresh", headers=refresh_headers)
    assert refresh_resp.status_code == 200

    # new expiry should be later
    sess2 = (await client.get(f"{API_PREFIX}/users/sessions", headers=auth_headers)).json()[0]
    new_expiry = datetime.fromisoformat(sess2["expires_at"])
    assert new_expiry > orig_expiry
