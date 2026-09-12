import asyncio
import os
import sys
from typing import Any, AsyncGenerator, Generator

# Ensure the 'api' module can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pylint: disable=wrong-import-position
import asyncpg
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from api.apps.notification.v0.channels.websocket import connection_manager
from api.constants import Environments
from api.core.config import settings
from api.core.database import DataBase
from api.core.events import event_bus
from api.core.rate_limit import limiter
from api.core.redis import get_redis, redis_client, redis_event_bus, redis_socket
from api.main import app
from migrate import apply_migrations, create_migrations_table


def pytest_configure(config: Any) -> None:  # pylint: disable=unused-argument
    """
    Initial configuration and test database setup.
    Isolates workers when running with xdist.
    """
    settings.ENV = Environments.TEST.value
    settings.SECRET_KEY = "a_very_long_and_secure_test_secret_key_32_chars"
    limiter.enabled = False

    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    if worker_id:
        settings.TEST_DATABASE_URL += f"_{worker_id}"

    async def setup_db() -> None:
        # Extract base connection info and database name
        base_url = settings.TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
        db_name = settings.TEST_DATABASE_URL.rsplit("/", 1)[1]

        try:
            sys_conn = await asyncpg.connect(base_url)
            try:
                if worker_id:
                    # Ensure clean state for xdist workers
                    await sys_conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
                    await sys_conn.execute(f'CREATE DATABASE "{db_name}"')
                else:
                    # Ensure DB exists for non-xdist runs
                    exists = await sys_conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
                    if not exists:
                        await sys_conn.execute(f'CREATE DATABASE "{db_name}"')
            finally:
                await sys_conn.close()
        except asyncpg.PostgresError as e:
            print(f"Database initialization warning: {e}")

        # Initialize schema and run migrations
        pool = await asyncpg.create_pool(settings.TEST_DATABASE_URL)
        if not pool:
            raise RuntimeError("Failed to create database pool during setup")

        try:
            async with pool.acquire() as conn:
                await conn.execute("DROP SCHEMA IF EXISTS public CASCADE;")
                await conn.execute("CREATE SCHEMA public;")
                await conn.execute("GRANT ALL ON SCHEMA public TO public;")

            await create_migrations_table(pool)
            await apply_migrations(pool, direction="up")
            print(f"Test database setup complete for worker: {worker_id or 'main'}")
        finally:
            await pool.close()

    asyncio.run(setup_db())


def pytest_unconfigure(config: Any) -> None:  # pylint: disable=unused-argument
    """
    Cleanup after test suite completion.
    Drops worker-specific databases.
    """

    async def teardown_db() -> None:
        worker_id = os.environ.get("PYTEST_XDIST_WORKER")

        if worker_id:
            base_url = settings.TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
            db_name = settings.TEST_DATABASE_URL.rsplit("/", 1)[1]
            try:
                sys_conn = await asyncpg.connect(base_url)
                try:
                    await sys_conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
                finally:
                    await sys_conn.close()
            except asyncpg.PostgresError:
                pass
        else:
            # Revert main test database migrations
            pool = await asyncpg.create_pool(settings.TEST_DATABASE_URL)
            if pool:
                try:
                    await apply_migrations(pool, direction="down", steps=None)
                finally:
                    await pool.close()

    asyncio.run(teardown_db())


@pytest.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:
    """
    Main asynchronous test client fixture.
    Handles database pool isolation, Redis client resets, and listener lifecycle.
    """
    # Store and override settings
    original_primary_url = settings.PRIMARY_DATABASE_URL
    original_replica_url = settings.REPLICA_DATABASE_URL
    settings.PRIMARY_DATABASE_URL = settings.TEST_DATABASE_URL
    settings.REPLICA_DATABASE_URL = settings.TEST_DATABASE_URL

    try:
        # Initialize singleton database instance for the test
        db_instance = DataBase()
        await db_instance.create_pool(
            write_uri=settings.TEST_DATABASE_URL,
            read_uris={"global": [settings.TEST_DATABASE_URL]},
            loop=asyncio.get_running_loop(),
        )

        # Reset global Redis clients to the current event loop
        redis_client.client = Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB, decode_responses=True
        )
        redis_socket.client = Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB_SOCKET, decode_responses=True
        )
        redis_event_bus.client = Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB_EVENT_BUS, decode_responses=True
        )

        # Clean reset of pubsub listeners
        await event_bus.stop()
        await connection_manager.stop()

        event_bus.pubsub = redis_event_bus.client.pubsub()
        connection_manager.pubsub = redis_socket.client.pubsub()
        event_bus.listener_task = None
        connection_manager.listener_task = None

        await event_bus.start()

        # Dependency injections
        async def mock_get_redis() -> AsyncGenerator[Redis, None]:
            r_client = Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True,
            )
            try:
                yield r_client
            finally:
                await r_client.aclose()

        app.dependency_overrides[get_redis] = mock_get_redis

        # Execute tests
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c

        # Teardown
        app.dependency_overrides.clear()
        await event_bus.stop()
        await connection_manager.stop()
        await db_instance.close_pool()

        for r_inst in [redis_client.client, redis_socket.client, redis_event_bus.client]:
            if r_inst:
                await r_inst.aclose()

    finally:
        settings.PRIMARY_DATABASE_URL = original_primary_url
        settings.REPLICA_DATABASE_URL = original_replica_url


@pytest.fixture(scope="function")
def sync_client() -> Generator[TestClient, None, None]:
    """
    Synchronous TestClient fixture, primarily for WebSocket testing.
    Replicates settings overrides from the async client.
    """
    original_primary_url = settings.PRIMARY_DATABASE_URL
    original_replica_url = settings.REPLICA_DATABASE_URL
    settings.PRIMARY_DATABASE_URL = settings.TEST_DATABASE_URL
    settings.REPLICA_DATABASE_URL = settings.TEST_DATABASE_URL

    try:
        app.dependency_overrides[get_redis] = lambda: Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True
        )

        with TestClient(app) as tc:
            yield tc

        app.dependency_overrides.clear()
    finally:
        settings.PRIMARY_DATABASE_URL = original_primary_url
        settings.REPLICA_DATABASE_URL = original_replica_url


@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[DataBase, None]:
    """Fixture providing an initialized DataBase instance connected to the test database."""
    db_instance = DataBase()
    await db_instance.create_pool(
        write_uri=settings.TEST_DATABASE_URL,
        read_uris={"global": [settings.TEST_DATABASE_URL]},
        loop=asyncio.get_running_loop(),
    )
    try:
        yield db_instance
    finally:
        await db_instance.close_pool()
