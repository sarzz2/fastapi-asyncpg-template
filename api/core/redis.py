import logging
from typing import AsyncGenerator

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from api.core.config import settings

logger = logging.getLogger("fastapi")


class RedisClient:
    """Redis client wrapper for asynchronous operations."""

    def __init__(
        self,
        host: str = settings.REDIS_HOST,
        port: int = settings.REDIS_PORT,
        db: int = settings.REDIS_DB,
        decode_responses: bool = True,
    ):
        self.client = Redis(host=host, port=port, db=db, decode_responses=decode_responses)

    async def connect(self) -> None:
        """Connect to the Redis server and verify the connection."""
        try:
            pong = await self.client.ping()
            if not pong:
                raise RuntimeError("Redis ping returned falsy response")

            logger.info("Connected to Redis successfully.")
        except Exception as exc:
            logger.critical("Failed to connect to Redis: %s", exc)
            raise RuntimeError("Redis connection failed") from exc

    async def close(self) -> None:
        """Close the connection to the Redis server."""
        await self.client.aclose()
        logger.info("Closed Redis connection.")

    async def health_check(self) -> bool:
        """Check the health of the Redis connection."""
        try:
            return await self.client.ping()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Redis health check failed: %s", exc)
            return False


# Specialized Redis clients for logical separation
redis_client = RedisClient(db=settings.REDIS_DB)
redis_socket = RedisClient(db=settings.REDIS_DB_SOCKET)
redis_event_bus = RedisClient(db=settings.REDIS_DB_EVENT_BUS)


async def get_redis() -> Redis:
    """Dependency to get the Redis client (default cache)."""
    return redis_client.client


async def listen_to_pubsub(pubsub: PubSub | None) -> AsyncGenerator[tuple[str, str], None]:
    """Yields (channel, data) from a Redis Pub/Sub subscription."""
    if not pubsub:
        return
    async for message in pubsub.listen():
        if message["type"] == "message":
            yield message["channel"], message["data"]
