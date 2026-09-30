"""
Unit tests for distributed Redis idempotency lock and response caching.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Response

from api.core.idempotency import IdempotencyManager


@pytest.mark.asyncio
async def test_idempotency_acquire_and_release_lock() -> None:
    """Verify distributed lock acquisition and release behavior."""
    with patch("api.core.idempotency.get_redis") as mock_get_redis:
        mock_redis = AsyncMock()
        mock_redis.set.return_value = True
        mock_redis.delete.return_value = 1
        mock_get_redis.return_value = mock_redis

        acquired = await IdempotencyManager.acquire_lock("test-key-123")
        assert acquired is True
        mock_redis.set.assert_awaited_once_with("idempotency:lock:test-key-123", "in-progress", ex=60, nx=True)

        await IdempotencyManager.release_lock("test-key-123")
        mock_redis.delete.assert_awaited_once_with("idempotency:lock:test-key-123")


@pytest.mark.asyncio
async def test_idempotency_cache_and_get_response() -> None:
    """Verify caching responses and retrieving cached responses."""
    with patch("api.core.idempotency.get_redis") as mock_get_redis:
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        # Cache response
        resp = Response(content='{"status":"ok"}', status_code=200, media_type="application/json")
        await IdempotencyManager.cache_response("test-key-123", resp)
        mock_redis.set.assert_awaited_once()

        # Get cached response
        mock_redis.get.return_value = json.dumps(
            {"status_code": 200, "headers": {}, "content": '{"status":"ok"}', "media_type": "application/json"}
        )
        cached = await IdempotencyManager.get_cached_response("test-key-123")
        assert cached is not None
        assert cached.status_code == 200
        assert cached.body == b'{"status":"ok"}'
