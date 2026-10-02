from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.apps.user.v0.dao.role import RoleDAO
from api.apps.user.v0.dao.user import UserDAO
from api.apps.user.v0.schemas.role import RoleData
from api.apps.user.v0.schemas.user import UserData
from api.apps.user.v0.service.auth import AuthService
from api.constants import TokenTypes
from api.core.auth import create_impersonation_token, verify_token
from api.core.context import CURRENT_IMPERSONATOR_ID
from api.core.dependencies import disallow_impersonation
from api.shared.redis_keys import RedisKeys


def _create_mock_user(
    user_id: UUID | None = None,
    username: str = "testuser",
    email: str = "test@example.com",
    is_active: bool = True,
    roles: list[RoleData] | None = None,
) -> UserData:
    return UserData(
        id=user_id or uuid4(),
        username=username,
        email=email,
        is_active=is_active,
        hashed_password="hashed_test_password",
        full_name="Test User",
        roles=roles or [],
        created_at=datetime.now(timezone.utc),
        token_version=1,
    )


def _create_mock_redis() -> MagicMock:
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.mark.asyncio
async def test_impersonation_token_creation_and_verification() -> None:
    """Verify that impersonation tokens encode and decode RFC 8693 act claims correctly."""
    admin_id = uuid4()
    admin_username = "admin_user"
    target_id = uuid4()
    target_username = "target_client"

    token_data = {
        "sub": target_username,
        "id": str(target_id),
        "scopes": ["users:read"],
        "token_version": 1,
        "is_impersonation": True,
        "act": {
            "id": str(admin_id),
            "sub": admin_username,
        },
    }

    mock_redis = _create_mock_redis()
    token_details = create_impersonation_token(token_data, expire_minutes=15)
    token_str = token_details["token"]

    decoded = await verify_token(token_str, mock_redis, token_type=TokenTypes.ACCESS.value)

    assert decoded.username == target_username
    assert decoded.id == target_id
    assert decoded.is_impersonation is True
    assert decoded.impersonator_id == admin_id
    assert decoded.impersonator_username == admin_username


@pytest.mark.asyncio
async def test_disallow_impersonation_blocks_impersonated_tokens() -> None:
    """Verify disallow_impersonation dependency raises 403 on impersonated tokens."""
    token_data = {
        "sub": "target_user",
        "id": str(uuid4()),
        "scopes": [],
        "token_version": 1,
        "is_impersonation": True,
        "act": {
            "id": str(uuid4()),
            "sub": "admin",
        },
    }

    mock_redis = _create_mock_redis()
    token_details = create_impersonation_token(token_data)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_details["token"])

    with pytest.raises(HTTPException) as exc_info:
        await disallow_impersonation(credentials, mock_redis)

    assert exc_info.value.status_code == 403
    assert "active impersonation session" in exc_info.value.detail


@pytest.mark.asyncio
async def test_disallow_impersonation_allows_regular_tokens() -> None:
    """Verify disallow_impersonation passes without error for normal user tokens."""
    token_data = {
        "sub": "regular_user",
        "id": str(uuid4()),
        "scopes": [],
        "token_version": 1,
        "is_impersonation": False,
    }

    mock_redis = _create_mock_redis()
    token_details = create_impersonation_token(token_data)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_details["token"])

    # Should not raise any exception
    await disallow_impersonation(credentials, mock_redis)


@pytest.mark.asyncio
async def test_impersonate_self_rejected() -> None:
    """Verify admin cannot impersonate themselves."""
    admin_id = uuid4()
    admin_user = _create_mock_user(user_id=admin_id, username="admin")

    mock_user_dao = AsyncMock(spec=UserDAO)
    mock_role_dao = AsyncMock(spec=RoleDAO)
    mock_redis = _create_mock_redis()
    mock_request = MagicMock()

    service = AuthService(user_dao=mock_user_dao, role_dao=mock_role_dao, redis=mock_redis)

    with pytest.raises(HTTPException) as exc_info:
        await service.impersonate_user(
            admin_user=admin_user,
            target_user_id=admin_id,
            reason="testing",
            request=mock_request,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_impersonate_nested_rejected() -> None:
    """Verify nested impersonation is blocked when CURRENT_IMPERSONATOR_ID is already active."""
    admin_id = uuid4()
    target_id = uuid4()
    admin_user = _create_mock_user(user_id=admin_id, username="admin")

    mock_user_dao = AsyncMock(spec=UserDAO)
    mock_role_dao = AsyncMock(spec=RoleDAO)
    mock_redis = _create_mock_redis()
    mock_request = MagicMock()

    service = AuthService(user_dao=mock_user_dao, role_dao=mock_role_dao, redis=mock_redis)

    token = CURRENT_IMPERSONATOR_ID.set(str(uuid4()))
    try:
        with pytest.raises(HTTPException) as exc_info:
            await service.impersonate_user(
                admin_user=admin_user,
                target_user_id=target_id,
                reason="testing nested",
                request=mock_request,
            )
        assert exc_info.value.status_code == 400
    finally:
        CURRENT_IMPERSONATOR_ID.reset(token)


@pytest.mark.asyncio
async def test_impersonate_admin_rejected() -> None:
    """Verify admin cannot impersonate other admin accounts."""
    admin_id = uuid4()
    admin_user = _create_mock_user(user_id=admin_id, username="admin")

    super_admin_role = RoleData(
        id=uuid4(),
        name="Super Admin",
        description="Super Administrator",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    target_admin = _create_mock_user(user_id=uuid4(), username="root", roles=[super_admin_role])

    mock_user_dao = AsyncMock(spec=UserDAO)
    mock_user_dao.get_by_id.return_value = target_admin
    mock_role_dao = AsyncMock(spec=RoleDAO)
    mock_redis = _create_mock_redis()
    mock_request = MagicMock()

    service = AuthService(user_dao=mock_user_dao, role_dao=mock_role_dao, redis=mock_redis)

    with pytest.raises(HTTPException) as exc_info:
        await service.impersonate_user(
            admin_user=admin_user,
            target_user_id=target_admin.id,
            reason="testing admin target",
            request=mock_request,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_impersonate_user_success_flow() -> None:
    """Verify happy path of starting and stopping impersonation."""
    admin_id = uuid4()
    admin_user = _create_mock_user(user_id=admin_id, username="admin_alice")
    target_id = uuid4()
    target_user = _create_mock_user(user_id=target_id, username="client_bob")

    mock_user_dao = AsyncMock(spec=UserDAO)
    mock_user_dao.get_by_id.return_value = target_user
    mock_role_dao = AsyncMock(spec=RoleDAO)
    mock_redis = _create_mock_redis()
    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers.get.return_value = "pytest-agent"

    service = AuthService(user_dao=mock_user_dao, role_dao=mock_role_dao, redis=mock_redis)

    # 1. Start impersonation
    response = await service.impersonate_user(
        admin_user=admin_user,
        target_user_id=target_id,
        reason="diagnosing issue #102",
        request=mock_request,
        duration_minutes=20,
    )

    assert response.token.access_token is not None
    assert response.token.refresh_token == ""
    assert response.target_user.username == "client_bob"
    assert response.impersonator.id == admin_id
    assert response.impersonator.username == "admin_alice"

    # Verify Redis session key was set with TTL (20 minutes = 1200 seconds)
    mock_redis.set.assert_called()
    called_key = mock_redis.set.call_args_list[0][0][0]
    assert called_key.startswith("impersonation:session:")
    assert mock_redis.set.call_args_list[0][1]["ex"] == 1200

    # 2. Stop impersonation
    mock_redis.get.return_value = f'{{"target_user_id": "{target_id}"}}'
    jti = called_key.split(":")[-1]

    await service.stop_impersonation(jti=jti, admin_id=admin_id)

    # Verify token blacklisted in Redis
    mock_redis.set.assert_any_call(f"blacklist:access:{jti}", "1", ex=3600)
    # Verify session deleted from Redis
    mock_redis.delete.assert_called_with(RedisKeys.IMPERSONATION_SESSION.format(jti=jti))
