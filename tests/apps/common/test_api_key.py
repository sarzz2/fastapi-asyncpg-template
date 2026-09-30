"""
Unit tests for API key service, hashing, verification, and authentication dependencies.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import SecurityScopes

from api.apps.common.v0.dao.api_key import ApiKeyDAO
from api.apps.common.v0.schemas.api_key import ApiKeyCreate, ApiKeyData
from api.apps.common.v0.service.api_key import ApiKeyService
from api.core.dependencies import get_api_key
from api.core.redis import RedisClient


def _create_sample_api_key() -> ApiKeyData:
    """Generate a valid sample ApiKeyData instance for testing."""
    return ApiKeyData(
        id=uuid4(),
        created_by=uuid4(),
        name="Test Integration",
        prefix="ak_live_testpref",
        scopes=["users:read", "webhooks:read"],
        rate_limit=100,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        last_used_at=None,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_create_api_key() -> None:
    """Verify creating a new API key and returning raw key with prefix."""
    sample_key = _create_sample_api_key()
    mock_dao = AsyncMock(spec=ApiKeyDAO)
    mock_dao.create_api_key.return_value = sample_key

    mock_redis = MagicMock(spec=RedisClient)
    mock_redis.client = AsyncMock()

    service = ApiKeyService(dao=mock_dao, redis=mock_redis)
    payload = ApiKeyCreate(name="Test Integration", scopes=["users:read"])

    res = await service.create_api_key(payload, created_by=sample_key.created_by)

    assert res.name == sample_key.name
    assert res.key.startswith("ak_live_")
    mock_dao.create_api_key.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_api_key_valid() -> None:
    """Verify successful verification of active and unexpired API key."""
    sample_key = _create_sample_api_key()
    mock_dao = AsyncMock(spec=ApiKeyDAO)
    mock_dao.get_api_key_by_hash.return_value = sample_key

    mock_redis = MagicMock(spec=RedisClient)
    mock_redis.client = AsyncMock()
    mock_redis.client.set.return_value = True

    service = ApiKeyService(dao=mock_dao, redis=mock_redis)
    raw_key = "ak_live_test_secret_000000000000"  # gitleaks:allow

    res = await service.verify_api_key(raw_key)

    assert res is not None
    assert res.id == sample_key.id
    mock_dao.get_api_key_by_hash.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_api_key_expired() -> None:
    """Verify expired API keys fail validation and return None."""
    sample_key = _create_sample_api_key()
    sample_key.expires_at = datetime.now(timezone.utc) - timedelta(days=1)

    mock_dao = AsyncMock(spec=ApiKeyDAO)
    mock_dao.get_api_key_by_hash.return_value = sample_key

    mock_redis = MagicMock(spec=RedisClient)
    mock_redis.client = AsyncMock()

    service = ApiKeyService(dao=mock_dao, redis=mock_redis)
    res = await service.verify_api_key("ak_live_expiredkey")
    assert res is None


@pytest.mark.asyncio
async def test_rotate_api_key() -> None:
    """Verify rotating an API key invalidates cache and updates hash."""
    sample_key = _create_sample_api_key()
    sample_key.hashed_key = "old_hash"

    mock_dao = AsyncMock(spec=ApiKeyDAO)
    mock_dao.get_api_key_by_id.return_value = sample_key
    mock_dao.rotate_api_key.return_value = sample_key

    mock_redis = MagicMock(spec=RedisClient)
    mock_redis.client = AsyncMock()

    service = ApiKeyService(dao=mock_dao, redis=mock_redis)
    res = await service.rotate_api_key(sample_key.id)

    assert res.key.startswith("ak_live_")
    mock_dao.get_api_key_by_id.assert_awaited_once_with(sample_key.id)
    mock_dao.rotate_api_key.assert_awaited_once()
    mock_redis.client.delete.assert_awaited_once_with("api_key:cache:old_hash")


@pytest.mark.asyncio
async def test_delete_api_key() -> None:
    """Verify deleting an API key removes record and invalidates cache."""
    sample_key = _create_sample_api_key()
    sample_key.hashed_key = "old_hash"

    mock_dao = AsyncMock(spec=ApiKeyDAO)
    mock_dao.get_api_key_by_id.return_value = sample_key
    mock_dao.delete_api_key.return_value = True

    mock_redis = MagicMock(spec=RedisClient)
    mock_redis.client = AsyncMock()

    service = ApiKeyService(dao=mock_dao, redis=mock_redis)
    await service.delete_api_key(sample_key.id)

    mock_dao.get_api_key_by_id.assert_awaited_once_with(sample_key.id)
    mock_dao.delete_api_key.assert_awaited_once_with(sample_key.id)
    mock_redis.client.delete.assert_awaited_once_with("api_key:cache:old_hash")


@pytest.mark.asyncio
async def test_get_api_key_dependency_success() -> None:
    """Verify FastAPI security dependency resolves valid key with required scopes."""
    sample_key = _create_sample_api_key()
    mock_service = AsyncMock(spec=ApiKeyService)
    mock_service.verify_api_key.return_value = sample_key

    res = await get_api_key(
        security_scopes=SecurityScopes(scopes=["users:read"]),
        raw_key="ak_live_valid",
        service=mock_service,
    )
    assert res.id == sample_key.id


@pytest.mark.asyncio
async def test_get_api_key_dependency_insufficient_scope() -> None:
    """Verify dependency raises 403 Forbidden when requested scope is missing."""
    sample_key = _create_sample_api_key()
    mock_service = AsyncMock(spec=ApiKeyService)
    mock_service.verify_api_key.return_value = sample_key

    with pytest.raises(HTTPException) as exc_info:
        await get_api_key(
            security_scopes=SecurityScopes(scopes=["admin:write"]),
            raw_key="ak_live_valid",
            service=mock_service,
        )
    assert exc_info.value.status_code == 403
