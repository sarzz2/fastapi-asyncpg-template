import logging
from typing import Awaitable, cast

from redis.asyncio import Redis

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
