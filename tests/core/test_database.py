# pylint: disable=protected-access, import-outside-toplevel, redefined-outer-name, unused-argument
import asyncio
from typing import Any, Generator, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.core.database import DataBase, PoolMeta


@pytest.fixture(autouse=True)
async def cleanup_db() -> Any:
    """Cleanup database state."""
    # Reset DataBase class state before/after each test
    DataBase.write_pool = None
    DataBase.read_pools_by_region = {}
    if DataBase._health_task and not DataBase._health_task.done():
        DataBase._health_task.cancel()
    yield
    await DataBase.close_pool()


@pytest.fixture
def mock_postgres_db() -> Generator[MagicMock, None, None]:
    """Mock database instance."""
    with patch("api.core.database.DataBase") as mock:
        yield mock


@pytest.mark.asyncio
async def test_create_pool() -> None:
    """Test the creation of database pools."""
    from api.core.database import settings

    original_interval = settings.HEALTH_CHECK_INTERVAL
    settings.HEALTH_CHECK_INTERVAL = 0
    try:
        with patch("api.core.database.create_pool", new_callable=AsyncMock) as mock_create_pool:
            mock_pool = MagicMock()
            mock_create_pool.return_value = mock_pool

            await DataBase.create_pool(
                write_uri="postgres://write",
                read_uris={"us-east": ["postgres://read1"], "eu-west": ["postgres://read2"]},
            )

            assert DataBase.write_pool is not None
            assert "us-east" in DataBase.read_pools_by_region
            assert "eu-west" in DataBase.read_pools_by_region
            assert len(DataBase.read_pools_by_region["us-east"]) == 1

            # Verify calls
            assert mock_create_pool.call_count == 3  # 1 write + 2 reads
    finally:
        settings.HEALTH_CHECK_INTERVAL = original_interval


@pytest.mark.asyncio
async def test_choose_region_priority() -> None:
    """Test the logic for choosing a read region based on priority."""
    # Setup pools manually
    pool1 = MagicMock()
    pool2 = MagicMock()
    DataBase.read_pools_by_region = {
        "us-east": [PoolMeta(uri="u1", pool=pool1, region="us-east", healthy=True)],
        "eu-west": [PoolMeta(uri="u2", pool=pool2, region="eu-west", healthy=True)],
    }

    # 1. Client region match
    assert await DataBase._choose_region(client_region="eu-west") == "eu-west"

    # 2. Priority list
    DataBase._region_priority = ["us-east", "eu-west"]
    assert await DataBase._choose_region(client_region="unknown") == "us-east"

    # 3. Latency fallback
    # mark us-east unhealthy or latency check?
    DataBase._region_priority = []
    DataBase.read_pools_by_region["us-east"][0].last_latency = 0.5
    DataBase.read_pools_by_region["eu-west"][0].last_latency = 0.1
    assert await DataBase._choose_region(client_region="unknown") == "eu-west"


@pytest.mark.asyncio
async def test_select_read_pool_logic() -> None:
    """Test the logic for selecting a read pool."""
    pool1 = MagicMock()
    pool1.get_size.return_value = 5
    pool1.get_free_size.return_value = 5

    DataBase.read_pools_by_region = {"us-east": [PoolMeta(uri="u1", pool=pool1, region="us-east", healthy=True)]}

    # Select pool
    pool, region = await DataBase._select_read_pool(client_region="us-east")
    assert pool == pool1
    assert region == "us-east"

    # Fallback to write pool if no read pools
    DataBase.read_pools_by_region = {}
    DataBase.write_pool = MagicMock()
    pool, region = await DataBase._select_read_pool()
    assert pool == DataBase.write_pool

    # Error if nothing available
    DataBase.write_pool = None
    with pytest.raises(RuntimeError):
        await DataBase._select_read_pool()


@pytest.mark.asyncio
async def test_health_check(mock_postgres_db: MagicMock) -> None:
    """Test database health check."""
    # health_check verifies read_pools_by_region.
    # We need to mock the internal state or the method result if patching.
    # Since we are testing DataBase methods, we should probably mock get_pool and friends?
    # Or simpler: DataBase.health_check iterates read_pools_by_region.
    # We can perform a rudimentary test.
    # But since DataBase is a class with ClassVars, we need to be careful not to pollute.

    # Setup state
    DataBase.read_pools_by_region = {"us-east-1": [MagicMock(healthy=True, last_latency=0.1), MagicMock(healthy=False)]}

    health = await DataBase.health_check()
    assert "us-east-1" in health
    assert health["us-east-1"]["healthy_pools"] == 1
    assert health["us-east-1"]["total_pools"] == 2
    assert health["us-east-1"]["avg_latency"] == 0.1

    # Cleanup
    DataBase.read_pools_by_region = {}


@pytest.mark.asyncio
async def test_get_db_dependency() -> None:
    """Test get_db dependency."""
    # get_db is a generator that yields DataBase class
    from api.core.database import get_db

    gen = get_db()
    db = await anext(gen)
    assert db == DataBase


@pytest.mark.asyncio
async def test_fetch_query() -> None:
    """Test fetching data from the database."""
    # Setup mocks
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[MagicMock(dict=lambda: {"id": 1})])
    mock_pool.fetchrow = AsyncMock(return_value=MagicMock(dict=lambda: {"id": 1}))

    with patch("api.core.database.DataBase.get_pool", return_value=(mock_pool, "test-region")):
        # Test fetch list
        res = await DataBase.fetch("SELECT * FROM table")
        assert res is not None
        assert len(cast(list[Any], res)) == 1
        mock_pool.fetch.assert_called_once()

        # Test fetch row
        res_row = await DataBase.fetch("SELECT 1", fetch_row=True)
        assert res_row is not None
        mock_pool.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_write_query() -> None:
    """Test writing data to the database."""
    mock_pool = MagicMock()
    mock_pool.fetchrow = AsyncMock(return_value=MagicMock(dict=lambda: {"id": 1}))

    # We mock get_pool(use_primary=True)
    with patch("api.core.database.DataBase.get_pool") as mock_get_pool:
        mock_get_pool.return_value = (mock_pool, "primary")

        await DataBase.write("INSERT INTO foo VALUES (1)")
        mock_pool.fetchrow.assert_called()
        mock_get_pool.assert_called_with(use_primary=True)


@pytest.mark.asyncio
async def test_execute_query() -> None:
    """Test executing a query that returns a command tag."""
    mock_pool = MagicMock()
    mock_pool.execute = AsyncMock(return_value="INSERT 0 1")

    DataBase.write_pool = mock_pool

    tag = await DataBase.execute("INSERT INTO foo VALUES (1)")
    assert tag == "INSERT 0 1"
    mock_pool.execute.assert_called()


@pytest.mark.asyncio
async def test_health_check_loop_logic() -> None:
    """Test health check loop logic."""
    # Test one iteration of health check
    pool1 = MagicMock()
    # pool1.acquire() returns an async context manager.
    # We need to mock the context manager's __aenter__ to return the connection.
    pool1.get_size.return_value = 10
    pool1.get_free_size.return_value = 5

    mock_cm = MagicMock()
    mock_conn = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    pool1.acquire.return_value = mock_cm

    DataBase.read_pools_by_region = {"us-east": [PoolMeta(uri="u1", pool=pool1, region="us-east", healthy=False)]}

    with patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError]):
        # Run loop
        try:
            await DataBase._health_check_loop(1)
        except asyncio.CancelledError:
            pass

    # Check if healthy status was updated
    assert DataBase.read_pools_by_region["us-east"][0].healthy is True
    mock_conn.fetchval.assert_called_with("SELECT 1")


@pytest.mark.asyncio
async def test_database_error_handling() -> None:
    """Test error handling in execute and fetch."""
    mock_pool = MagicMock()
    mock_pool.execute.side_effect = Exception("DB Error")
    mock_pool.fetch.side_effect = Exception("Fetch Error")

    DataBase.write_pool = mock_pool

    with pytest.raises(Exception):
        await DataBase.execute("SELECT 1")

    # Test get_pool error when NO pools
    DataBase.write_pool = None
    DataBase.read_pools_by_region = {}
    with pytest.raises(RuntimeError):
        await DataBase.fetch("SELECT 1")
