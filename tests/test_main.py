"""
Tests for the main application entry point, including lifespan management and global middlewares.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request, Response
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from api.main import app, lifespan, log_requests


@pytest.fixture
def test_client() -> TestClient:
    """Provides a basic TestClient for the FastAPI app."""
    return TestClient(app)


@pytest.mark.asyncio
async def test_health_check_states() -> None:
    """
    Verify health check endpoint responses across various service statuses (up, down, degraded).
    """
    with (
        patch("api.main.DataBase.health_check", new_callable=AsyncMock) as mock_db,
        patch("api.main.redis_client.health_check", new_callable=AsyncMock) as mock_redis,
    ):
        # 1. Healthy State
        mock_db.return_value = {"primary": {"healthy_pools": 1, "total_pools": 1, "avg_latency": 0.01}}
        mock_redis.return_value = True

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            assert response.json()["database"]["status"] == "up"

            # 2. Database Down
            mock_db.return_value = {"primary": {"healthy_pools": 0, "total_pools": 1, "avg_latency": 0.0}}
            response = await client.get("/health")
            assert response.json()["database"]["status"] == "down"

            # 3. Database Degraded
            mock_db.return_value = {"primary": {"healthy_pools": 1, "total_pools": 2, "avg_latency": 0.01}}
            response = await client.get("/health")
            assert response.json()["database"]["status"] == "degraded"


@pytest.mark.asyncio
async def test_request_logging_middleware() -> None:
    """
    Verify that the log_requests middleware correctly logs request lifecycle and errors.
    """
    request = MagicMock(spec=Request)
    request.method, request.url, request.query_params = "GET", "http://test", {}

    async def mock_next_success(_req: Request) -> Response:
        return Response(status_code=200)

    async def mock_next_failure(_req: Request) -> Response:
        return Response(status_code=500)

    with patch("api.main.logger") as mock_logger:
        await log_requests(request, mock_next_success)
        assert mock_logger.info.call_count >= 2

        # Should catch and log, not propagate
        await log_requests(request, mock_next_failure)
        mock_logger.error.assert_called()


@pytest.mark.asyncio
async def test_application_lifespan_lifecycle() -> None:
    """
    Verify that all core services (DB, Redis, EventBus) are correctly initialized and closed
    during application lifespan.
    """
    with (
        patch("api.main.DataBase") as MockDB,
        patch("api.main.redis_client") as m_cache,
        patch("api.main.redis_socket") as m_sock,
        patch("api.main.redis_event_bus") as m_eb_redis,
        patch("api.main.event_bus") as m_eb,
        patch("api.main.connection_manager") as m_conn,
        patch("api.main.check_all_migrations_applied", new_callable=AsyncMock) as m_migrate,
        patch("api.main.logger"),
    ):
        m_migrate.return_value = True
        db_inst = MockDB.return_value

        # Setup async mocks for all lifecycle methods
        db_inst.create_pool = AsyncMock()
        db_inst.close_pool = AsyncMock()
        m_cache.connect = AsyncMock()
        m_cache.close = AsyncMock()
        m_sock.connect = AsyncMock()
        m_sock.close = AsyncMock()
        m_eb_redis.connect = AsyncMock()
        m_eb_redis.close = AsyncMock()
        m_eb.start = AsyncMock()
        m_eb.stop = AsyncMock()
        m_conn.stop = AsyncMock()

        async with lifespan(MagicMock()):
            db_inst.create_pool.assert_called_once()
            m_migrate.assert_called_once()
            m_eb.start.assert_called_once()

        db_inst.close_pool.assert_called_once()
        m_eb.stop.assert_called_once()
        m_conn.stop.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_failure_on_pending_migrations() -> None:
    """
    Verify that the application fails to start if there are pending database migrations.
    """
    with (
        patch("api.main.DataBase") as MockDB,
        patch("api.main.redis_client") as m_cache,
        patch("api.main.redis_socket") as m_sock,
        patch("api.main.redis_event_bus") as m_eb_redis,
        patch("api.main.event_bus") as m_eb,
        patch("api.main.check_all_migrations_applied", new_callable=AsyncMock) as m_migrate,
        patch("api.main.logger"),
    ):
        m_migrate.return_value = False
        db_inst = MockDB.return_value
        db_inst.create_pool = AsyncMock()
        m_cache.connect = AsyncMock()
        m_sock.connect = AsyncMock()
        m_eb_redis.connect = AsyncMock()
        m_eb.start = AsyncMock()

        with pytest.raises(RuntimeError, match="pending migrations"):
            async with lifespan(MagicMock()):
                pass
