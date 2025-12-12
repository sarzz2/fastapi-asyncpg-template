# pylint: disable=redefined-outer-name, redefined-builtin
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from api.core.cache import cache, cache_invalidate


class Item(BaseModel):
    """Item model."""

    id: int
    name: str


@pytest.fixture
def mock_redis() -> Any:
    """Mock Redis client."""
    with patch("api.core.cache.redis_client.client") as mock:
        # Setup pipeline mock
        pipeline_mock = MagicMock()
        pipeline_mock.execute = AsyncMock()

        # pipeline() returns a synchronous object that acts as async context manager
        pipeline_context_manager = MagicMock()
        pipeline_context_manager.__aenter__ = AsyncMock(return_value=pipeline_mock)
        pipeline_context_manager.__aexit__ = AsyncMock(return_value=None)

        # mock.pipeline must be a synchronous callable
        mock.pipeline = MagicMock(return_value=pipeline_context_manager)

        mock.get = AsyncMock()
        mock.set = AsyncMock()
        mock.hget = AsyncMock()
        mock.hset = AsyncMock()
        mock.expire = AsyncMock()
        mock.delete = AsyncMock()
        mock.hdel = AsyncMock()
        yield mock


@pytest.mark.asyncio
async def test_cache_decorator_hit(mock_redis: AsyncMock) -> None:
    """Test cache hit scenario."""
    mock_redis.get.return_value = '{"id": 1, "name": "cached"}'

    @cache(key_pattern="item:{id}", model=Item)
    async def get_item(id: int) -> Item:
        """Get item by id."""
        return Item(id=id, name="fresh")

    result = await get_item(id=1)
    assert result.name == "cached"
    mock_redis.get.assert_called_with("item:1")


@pytest.mark.asyncio
async def test_cache_decorator_miss(mock_redis: AsyncMock) -> None:
    """Test cache miss scenario."""
    mock_redis.get.return_value = None

    @cache(key_pattern="item:{id}", model=Item)
    async def get_item(id: int) -> Item:
        """Get item by id."""
        return Item(id=id, name="fresh")

    result = await get_item(id=1)
    assert result.name == "fresh"
    mock_redis.set.assert_called_once()
    args = mock_redis.set.call_args
    assert "item:1" in args[0]
    assert '"name":"fresh"' in args[0][1]


@pytest.mark.asyncio
async def test_cache_decorator_list(mock_redis: AsyncMock) -> None:
    """Test caching a list of items."""
    mock_redis.get.return_value = None

    @cache(key_pattern="items", model=Item)
    async def get_items() -> list[Item]:
        """Get list of items."""
        return [Item(id=1, name="a"), Item(id=2, name="b")]

    result = await get_items()
    assert len(result) == 2
    mock_redis.set.assert_called()
    args = mock_redis.set.call_args
    assert "[{" in args[0][1]


@pytest.mark.asyncio
async def test_cache_hash(mock_redis: AsyncMock) -> None:
    """Test caching using Redis hashes."""
    mock_redis.hget.return_value = None

    @cache(key_pattern="field:{id}", hash_key="myhash", model=Item)
    async def get_item(id: int) -> Item:
        """Get item by id."""
        return Item(id=id, name="fresh")

    await get_item(id=1)
    mock_redis.hget.assert_called_with("myhash", "field:1")
    mock_redis.hget.assert_called_with("myhash", "field:1")

    # Verify pipeline was used
    mock_redis.pipeline.assert_called()
    pipe_mock = mock_redis.pipeline.return_value.__aenter__.return_value
    pipe_mock.hset.assert_called()
    pipe_mock.expire.assert_called()
    pipe_mock.execute.assert_called()


@pytest.mark.asyncio
async def test_cache_invalidate(mock_redis: AsyncMock) -> None:
    """Test cache invalidation."""

    @cache_invalidate(key_pattern="item:{id}")
    async def update_item(id: int) -> bool:  # pylint: disable=unused-argument
        """Update item by id."""
        return True

    await update_item(id=1)
    mock_redis.delete.assert_called_with("item:1")


@pytest.mark.asyncio
async def test_cache_invalidate_list(mock_redis: AsyncMock) -> None:
    """Test invalidating multiple cache keys."""

    @cache_invalidate(key_pattern=["item:{id}", "list"])
    async def update_item(id: int) -> bool:  # pylint: disable=unused-argument
        """Update item by id."""
        return True

    await update_item(id=1)
    mock_redis.delete.assert_called()
    args = mock_redis.delete.call_args[0]
    assert "item:1" in args
    assert "list" in args


@pytest.mark.asyncio
async def test_cache_error_handling(mock_redis: AsyncMock) -> None:
    """Test error handling in cache decorator."""
    mock_redis.get.side_effect = Exception("Redis down")

    @cache(key_pattern="key")
    async def get_val() -> str:  # pylint: disable=redefined-builtin
        """Get value."""
        return "val"

    # Should not raise exception, but return fresh value and log warning
    res = await get_val()
    assert res == "val"
