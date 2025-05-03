import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import DataBase
from app.core.redis import RedisClient
from app.main import app
from migrate import apply_migrations, create_migrations_table, get_applied_migrations

API_PREFIX = "/api/v0"


# 1. Session-scoped event loop
@pytest.fixture(scope="session")
def event_loop():
    """Create session-scoped event loop"""
    try:
        import asyncio

        loop = asyncio.get_event_loop_policy().new_event_loop()
        yield loop
        loop.close()
    except RuntimeError:
        import uvloop

        uvloop.install()
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()


# 2. Session-scoped database setup
@pytest.fixture(scope="session")
async def database():
    """Session-scoped database fixture"""
    db = DataBase()
    await db.create_pool(settings.TEST_DATABASE_URL)
    await create_migrations_table(db.pool)
    await apply_migrations(db.pool)
    yield db
    res = await get_applied_migrations(db.pool)
    await apply_migrations(db.pool, "down", len(res))
    await db.close_pool()


# 3. Session-scoped Redis setup
@pytest.fixture(scope="session")
async def redis():
    """Session-scoped Redis fixture"""
    redis_client = RedisClient()
    await redis_client.connect()
    yield redis_client
    await redis_client.client.flushdb()
    await redis_client.close()


# 4. Transaction-per-test isolation
@pytest.fixture(autouse=True)
async def transactional_db(database):
    """Auto-rollback transactions for test isolation"""
    async with database.pool.acquire() as conn:
        async with conn.transaction():
            yield conn


# 5. HTTP client fixture
@pytest.fixture
async def client(database, redis):
    """Per-test HTTP client"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
