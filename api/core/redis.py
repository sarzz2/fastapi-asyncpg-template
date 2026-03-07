import logging
from typing import AsyncGenerator, Awaitable, cast

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from api.core.config import settings

log = logging.getLogger("fastapi")


class RedisClient:
    """Redis client wrapper for asynchronous operations."""

    def __init__(
        self,
        host: str = settings.REDIS_HOST,
        port: int = settings.REDIS_PORT,
        decode_responses: bool = True,
    ):
        self.client = Redis(host=host, port=port, decode_responses=decode_responses)

    async def connect(self) -> None:
        """Connect to the Redis server and verify the connection."""
        try:
            pong = await cast(Awaitable[bool], self.client.ping())
            if not pong:
                raise RuntimeError("Redis ping returned falsy response")

            log.info("Connected to Redis successfully.")
        except Exception as exc:
            log.critical("Failed to connect to Redis: %s", exc)
            raise RuntimeError("Redis connection failed") from exc

    async def close(self) -> None:
        """Close the connection to the Redis server."""
        await self.client.aclose()

    async def health_check(self) -> bool:
        """Check the health of the Redis connection."""
        try:
            return await cast(Awaitable[bool], self.client.ping())
        except Exception:  # pylint: disable=broad-except
            return False


redis_client = RedisClient()


async def get_redis() -> Redis:
    """Dependency to get the Redis client."""
    return redis_client.client


async def listen_to_pubsub(pubsub: PubSub) -> AsyncGenerator[tuple[str, str], None]:
    """Yields (channel, data) from a Redis Pub/Sub subscription."""
    if not pubsub:
        return
    async for message in pubsub.listen():
        if message["type"] == "message":
            yield message["channel"], message["data"]
