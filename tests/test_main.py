"""Tests for main application entrypoint."""
# pylint: disable=redefined-outer-name, unused-argument, import-outside-toplevel

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app, lifespan


@pytest.fixture
def client() -> TestClient:
    """Create a TestClient."""
    # We can mock the `lifespan` context manager itself or its internals.
    return TestClient(app)


def test_health_check_status_ok() -> None:
    """Test health check endpoint when all services are up."""
    # Mock DataBase.health_check
    with (
        patch("api.main.DataBase.health_check", new_callable=AsyncMock) as mock_db_health,
        patch("api.main.redis_client.health_check", new_callable=AsyncMock) as mock_redis_health,
    ):
        mock_db_health.return_value = {"primary": {"healthy_pools": 1, "total_pools": 1, "avg_latency": 0.01}}
        mock_redis_health.return_value = True

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"]["status"] == "up"
        assert data["redis"]["status"] == "up"


def test_health_check_db_down() -> None:
    """Test health check endpoint when database is down."""
    with (
        patch("api.main.DataBase.health_check", new_callable=AsyncMock) as mock_db_health,
        patch("api.main.redis_client.health_check", new_callable=AsyncMock) as mock_redis_health,
    ):
        mock_db_health.return_value = {"primary": {"healthy_pools": 0, "total_pools": 1, "avg_latency": 0.0}}
        mock_redis_health.return_value = True

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["database"]["status"] == "down"


def test_health_check_db_degraded() -> None:
    """Test health check endpoint when database is degraded."""
    with (
        patch("api.main.DataBase.health_check", new_callable=AsyncMock) as mock_db_health,
        patch("api.main.redis_client.health_check", new_callable=AsyncMock) as mock_redis_health,
    ):
        mock_db_health.return_value = {"primary": {"healthy_pools": 1, "total_pools": 2, "avg_latency": 0.01}}
        mock_redis_health.return_value = True

        client = TestClient(app)
        response = client.get("/health")
        data = response.json()
        assert data["database"]["status"] == "degraded"


@pytest.mark.asyncio
async def test_log_requests_direct() -> None:
    """Test log_requests middleware function directly."""
    # Unit test middleware function directly
    from fastapi import Request, Response

    from api.main import log_requests

    request = MagicMock(spec=Request)
    request.method = "GET"
    request.url = "http://test"
    request.query_params = {}

    async def call_next(req: Request) -> Response:
        return Response(status_code=200)

    with patch("api.main.logger") as mock_logger:
        await log_requests(request, call_next)
        # Should be called for request start and completion
        assert mock_logger.info.call_count >= 2

    async def call_next_error(req: Request) -> Response:
        return Response(status_code=500)

    with patch("api.main.logger") as mock_logger:
        await log_requests(request, call_next_error)
        mock_logger.error.assert_called()


def test_profile_request_middleware() -> None:
    """Test profile request middleware."""
    # Request with ?profile=true
    # Mock Profiler
    with patch("api.main.Profiler") as MockProfiler:
        instance = MockProfiler.return_value
        instance.output_html.return_value = "<html>Profile</html>"

        client = TestClient(app)
        response = client.get("/health?profile=true")

        assert response.status_code == 200
        assert instance.start.called
        assert instance.stop.called
        assert response.text == "<html>Profile</html>"


@pytest.mark.asyncio
async def test_lifespan_success() -> None:
    """Test lifespan startup and shutdown."""
    # Test lifespan logic
    mock_app = MagicMock()

    with (
        patch("api.main.DataBase") as MockDB,
        patch("api.main.redis_client") as mock_redis,
        patch("api.main.check_all_migrations_applied", new_callable=AsyncMock) as mock_migrate,
        patch("api.main.logger"),
    ):
        mock_migrate.return_value = True
        mock_db_instance = MockDB.return_value
        mock_db_instance.create_pool = AsyncMock()
        mock_db_instance.close_pool = AsyncMock()
        mock_redis.connect = AsyncMock()
        mock_redis.close = AsyncMock()

        async with lifespan(mock_app):
            mock_db_instance.create_pool.assert_called_once()
            mock_redis.connect.assert_called_once()
            mock_migrate.assert_called_once()

        mock_db_instance.close_pool.assert_called_once()
        mock_redis.close.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_migrations_failed() -> None:
    """Test lifespan when migrations fail."""
    mock_app = MagicMock()

    with (
        patch("api.main.DataBase") as MockDB,
        patch("api.main.redis_client") as mock_redis,
        patch("api.main.check_all_migrations_applied", new_callable=AsyncMock) as mock_migrate,
        patch("api.main.logger"),
    ):
        mock_migrate.return_value = False
        mock_db_instance = MockDB.return_value
        mock_db_instance.create_pool = AsyncMock()
        mock_redis.connect = AsyncMock()
        mock_redis.close = AsyncMock()  # Good practice to mock this too even if not reached depending on flow

        with pytest.raises(RuntimeError, match="You have pending migrations"):
            async with lifespan(mock_app):
                pass
