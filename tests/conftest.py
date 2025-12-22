import asyncio
import os
import sys
from typing import Any, AsyncGenerator, Generator

# Ensure the 'api' module can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pylint: disable=wrong-import-position
import asyncpg
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from api.core.config import settings
from api.core.database import DataBase
from api.core.rate_limit import limiter
from api.core.redis import get_redis
from api.main import app
from migrate import apply_migrations, create_migrations_table


def pytest_configure(config: Any) -> None:  # pylint: disable=unused-argument
    """Configure pytest and set up test database before any tests run."""
    settings.ENV = "test"
    limiter.enabled = False

    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    if worker_id:
        # Append worker_id to database name to isolate workers
        settings.TEST_DATABASE_URL += f"_{worker_id}"

    async def setup_db() -> None:
        # Create the test database if it doesn't exist
        # Connect to default 'postgres' db to create the test db
        base_url = settings.TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
        db_name = settings.TEST_DATABASE_URL.rsplit("/", 1)[1]

        try:
            sys_conn = await asyncpg.connect(base_url)
            try:
                # Check if DB exists
                exists = await sys_conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
                if not exists:
                    await sys_conn.execute(f'CREATE DATABASE "{db_name}"')
                elif worker_id:
                    # For workers, we might want to recreate it to ensure isolation
                    # But current logic was dropping it.
                    # Let's keep the drop logic for workers to ensure clean state
                    pass

                if worker_id:
                    # Recreate for worker isolation
                    await sys_conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
                    await sys_conn.execute(f'CREATE DATABASE "{db_name}"')

            finally:
                await sys_conn.close()
        except Exception as e:  # pylint: disable=broad-except
            # If we can't create DB (e.g. AWS RDS restrictions), we might fallback or fail.
            # For local dev, this should work.
            print(f"Database init warning: {e}")

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

            print(f"Test database setup complete for {settings.TEST_DATABASE_URL}")

        finally:
            await pool.close()

    # Run the async setup
    asyncio.run(setup_db())


def pytest_unconfigure(config: Any) -> None:  # pylint: disable=unused-argument
    """Clean up test database after all tests complete."""

    async def teardown_db() -> None:
        worker_id = os.environ.get("PYTEST_XDIST_WORKER")

        # If worker db, drop it? Or just leave it?
        # Dropping involves connecting to system db again.
        # It's cleaner to drop.

        if worker_id:
            base_url = settings.TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
            db_name = settings.TEST_DATABASE_URL.rsplit("/", 1)[1]

            try:
                sys_conn = await asyncpg.connect(base_url)
                try:
                    await sys_conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
                except Exception:  # pylint: disable=broad-except
                    pass
                finally:
                    await sys_conn.close()
            except Exception:  # pylint: disable=broad-except
                pass
            return

        # For main non-xdist run, we just down migrate as before
        pool = await asyncpg.create_pool(settings.TEST_DATABASE_URL, max_inactive_connection_lifetime=3)
        try:
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


@pytest.fixture(scope="function")
def sync_client() -> Generator[TestClient, None, None]:
    """Fixture for synchronous TestClient for WebSockets."""

    # We need to setup DB overrides similar to async client
    # But since this is a synchronous fixture, we can't easily do async DB setup here
    # if it wasn't done globally or by another fixture.
    # The 'client' fixture does setup/teardown.
    # Actually, we can make this fixture depend on the DB setup?
    # conftest.py's pytest_configure sets up DB.
    # But 'client' fixture overrides dependency settings.
    # Let's duplicate the settings override logic.
    original_primary_url = settings.PRIMARY_DATABASE_URL
    original_replica_url = settings.REPLICA_DATABASE_URL
    setattr(settings, "PRIMARY_DATABASE_URL", settings.TEST_DATABASE_URL)
    setattr(settings, "REPLICA_DATABASE_URL", settings.TEST_DATABASE_URL)

    # Override Redis?
    # TestClient calls app, app calls dependencies.
    # We need to override get_redis.
    # But get_redis returns async redis. TestClient runs async app in thread/loop?
    # Yes, TestClient handles async app.

    try:
        # We need an event loop for the app to run in TestClient?
        # TestClient creates its own portal.

        # Override Redis
        # We need to provide a Redis that works.
        # Since app connects to Redis, we can just let it connect to localhost Redis
        # or mock it.
        # The async client mock used "Redis" class.

        # We'll skip complex redis mocking and rely on integration
        # or use the same override if possible.

        app.dependency_overrides[get_redis] = lambda: Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True
        )

        with TestClient(app) as test_c:
            yield test_c

        app.dependency_overrides.clear()

    finally:
        settings.PRIMARY_DATABASE_URL = original_primary_url
        settings.REPLICA_DATABASE_URL = original_replica_url
