from unittest.mock import AsyncMock, patch

import pytest

from api.core.redis import RedisClient, get_redis


@pytest.mark.asyncio
async def test_redis_connect_success() -> None:
    """Test successful connection."""
    with patch("api.core.redis.Redis") as mock_redis_cls:
        mock_client = AsyncMock()
        mock_client.ping.return_value = True
        mock_redis_cls.return_value = mock_client

        client = RedisClient()
        await client.connect()

        mock_client.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_connect_ping_false() -> None:
    """Test connection fails if ping returns false."""
    with patch("api.core.redis.Redis") as mock_redis_cls:
        mock_client = AsyncMock()
        mock_client.ping.return_value = False
        mock_redis_cls.return_value = mock_client

        client = RedisClient()

        with pytest.raises(RuntimeError, match="Redis connection failed"):
            await client.connect()


@pytest.mark.asyncio
async def test_redis_connect_exception() -> None:
    """Test connection fails on exception."""
    with patch("api.core.redis.Redis") as mock_redis_cls:
        mock_client = AsyncMock()
        mock_client.ping.side_effect = Exception("Connection error")
        mock_redis_cls.return_value = mock_client

        client = RedisClient()

        with pytest.raises(RuntimeError, match="Redis connection failed"):
            await client.connect()


@pytest.mark.asyncio
async def test_redis_close() -> None:
    """Test closing connection."""
    with patch("api.core.redis.Redis") as mock_redis_cls:
        mock_client = AsyncMock()
        mock_redis_cls.return_value = mock_client

        client = RedisClient()
        await client.close()

        mock_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_check_success() -> None:
    """Test health check returns True on success."""
    with patch("api.core.redis.Redis") as mock_redis_cls:
        mock_client = AsyncMock()
        mock_client.ping.return_value = True
        mock_redis_cls.return_value = mock_client

        client = RedisClient()
        assert await client.health_check() is True


@pytest.mark.asyncio
async def test_health_check_failure() -> None:
    """Test health check returns False on exception."""
    with patch("api.core.redis.Redis") as mock_redis_cls:
        mock_client = AsyncMock()
        mock_client.ping.side_effect = Exception("Down")
        mock_redis_cls.return_value = mock_client

        client = RedisClient()
        assert await client.health_check() is False


@pytest.mark.asyncio
async def test_get_redis_dependency() -> None:
    """Test get_redis dependency."""
    client = await get_redis()
    assert client is not None
