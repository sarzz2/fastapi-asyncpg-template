import asyncio
from typing import Any, AsyncGenerator

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from api.core.config import settings
from api.core.database import DataBase
from api.core.redis import get_redis
from api.main import app
from migrate import apply_migrations, create_migrations_table


def pytest_configure(config: Any) -> None:  # pylint: disable=unused-argument
    """Configure pytest and set up test database before any tests run.

    This hook runs once before the test session starts and:
    1. Creates a connection to the test database
    2. Drops and recreates the public schema for clean state
    3. Runs all migrations

    Args:
        config: Pytest configuration object (unused but required by pytest).
    """

    async def setup_db() -> None:
        # Create connection pool to test database
        pool = await asyncpg.create_pool(settings.TEST_DATABASE_URL, max_inactive_connection_lifetime=3)

        try:
            # Drop and recreate public schema for completely clean state
            async with pool.acquire() as conn:
                await conn.execute("DROP SCHEMA IF EXISTS public CASCADE;")
                await conn.execute("CREATE SCHEMA public;")
                await conn.execute("GRANT ALL ON SCHEMA public TO public;")

            # Create migrations table and run all migrations
            await create_migrations_table(pool)
            await apply_migrations(pool, direction="up")

            print("Test database setup complete")

        finally:
            await pool.close()

    # Run the async setup
    asyncio.run(setup_db())


def pytest_unconfigure(config: Any) -> None:  # pylint: disable=unused-argument
    """Clean up test database after all tests complete.

    This hook runs once after the test session ends and rolls back all
    migrations to clean up the test database.

    Args:
        config: Pytest configuration object (unused but required by pytest).
    """

    async def teardown_db() -> None:
        pool = await asyncpg.create_pool(settings.TEST_DATABASE_URL, max_inactive_connection_lifetime=3)

        try:
            # Roll back all migrations to clean up
            await apply_migrations(pool, direction="down", steps=None)

        finally:
            await pool.close()

    # Run the async teardown
    asyncio.run(teardown_db())


@pytest.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:  # pylint: disable=redefined-outer-name
    """Fixture for async client with test database configuration.

    This fixture:
    1. Overrides database URLs to use TEST_DATABASE_URL
    2. Overrides Redis dependency for test isolation
    3. Provides an AsyncClient for making HTTP requests
    4. Cleans up overrides after each test

    Yields:
        AsyncClient: Configured async HTTP client for testing the API.
    """
    # Override database settings to use test database
    original_primary_url = settings.PRIMARY_DATABASE_URL
    original_replica_url = settings.REPLICA_DATABASE_URL

    # Monkey patch settings to
    setattr(settings, "PRIMARY_DATABASE_URL", settings.TEST_DATABASE_URL)
    setattr(settings, "REPLICA_DATABASE_URL", settings.TEST_DATABASE_URL)

    try:
        # Create database pool with test database
        database_instance = DataBase()
        await database_instance.create_pool(
            write_uri=settings.TEST_DATABASE_URL,
            read_uris={"global": [settings.TEST_DATABASE_URL]},
        )

        # Override Redis dependency
        async def override_get_redis() -> AsyncGenerator[Redis, None]:
            redis_client = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)
            try:
                yield redis_client
            finally:
                await redis_client.aclose()

        app.dependency_overrides[get_redis] = override_get_redis

        # Provide test client
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c

        # Cleanup
        app.dependency_overrides.clear()
        await database_instance.close_pool()

    finally:
        # Restore original settings
        settings.PRIMARY_DATABASE_URL = original_primary_url
        settings.REPLICA_DATABASE_URL = original_replica_url
