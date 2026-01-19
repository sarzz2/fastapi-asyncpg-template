# pylint: disable=redefined-outer-name
"""Tests for api/core/cache.py coverage gaps."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.core.cache import _generate_key, _get_from_cache, _save_to_cache, cache, cache_invalidate


def test_generate_key_success() -> None:
    """Test _generate_key works with valid pattern."""

    def sample_func(user_id: str) -> str:
        return user_id

    result = _generate_key("user:{user_id}", sample_func, ("123",), {})
    assert result == "user:123"


def test_generate_key_missing_argument() -> None:
    """Test _generate_key raises ValueError when pattern has missing key."""

    def sample_func(user_id: str) -> str:
        return user_id

    with pytest.raises(ValueError, match="Failed to generate cache key"):
        _generate_key("user:{missing_key}", sample_func, ("123",), {})


@pytest.mark.asyncio
async def test_get_from_cache_miss() -> None:
    """Test _get_from_cache returns None on cache miss."""
    with patch("api.core.cache.redis_client") as mock_redis:
        mock_redis.client.get = AsyncMock(return_value=None)

        result = await _get_from_cache("test_key", None, None)

        assert result is None


@pytest.mark.asyncio
async def test_get_from_cache_exception() -> None:
    """Test _get_from_cache returns None on Redis exception."""
    with patch("api.core.cache.redis_client") as mock_redis:
        mock_redis.client.get = AsyncMock(side_effect=Exception("Redis error"))

        result = await _get_from_cache("test_key", None, None)

        assert result is None


@pytest.mark.asyncio
async def test_get_from_cache_hash_exception() -> None:
    """Test _get_from_cache with hash_key returns None on exception."""
    with patch("api.core.cache.redis_client") as mock_redis:
        mock_redis.client.hget = AsyncMock(side_effect=Exception("Redis error"))

        result = await _get_from_cache("test_key", "hash_key", None)

        assert result is None


@pytest.mark.asyncio
async def test_save_to_cache_exception() -> None:
    """Test _save_to_cache handles exception gracefully."""
    with patch("api.core.cache.redis_client") as mock_redis:
        mock_redis.client.set = AsyncMock(side_effect=Exception("Redis error"))

        # Should not raise
        await _save_to_cache("test_key", None, "value", 3600)


@pytest.mark.asyncio
async def test_save_to_cache_with_hash_exception() -> None:
    """Test _save_to_cache with hash_key handles exception gracefully."""
    with patch("api.core.cache.redis_client") as mock_redis:
        mock_pipeline = MagicMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.hset = MagicMock()
        mock_pipeline.expire = MagicMock()
        mock_pipeline.execute = AsyncMock(side_effect=Exception("Redis error"))

        mock_redis.client.pipeline = MagicMock(return_value=mock_pipeline)

        # Should not raise
        await _save_to_cache("test_key", "hash_key", "value", 3600)


@pytest.mark.asyncio
async def test_cache_decorator_key_generation_failure() -> None:
    """Test cache decorator falls back when key generation fails."""

    @cache(key_pattern="user:{missing_arg}")
    async def my_func(user_id: str) -> str:
        return f"result_{user_id}"

    # Should call the function directly without caching
    result = await my_func("123")
    assert result == "result_123"


@pytest.mark.asyncio
async def test_cache_invalidate_key_generation_failure() -> None:
    """Test cache_invalidate handles key generation failure gracefully."""

    @cache_invalidate(key_pattern="user:{missing_arg}")
    async def my_func(user_id: str) -> str:
        return f"result_{user_id}"

    # Should execute function and not raise on invalid key
    result = await my_func("123")
    assert result == "result_123"
