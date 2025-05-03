import logging

from redis.asyncio import Redis

from app.core.config import settings

log = logging.getLogger("fastapi")


class RedisClient:
    def __init__(self, host=settings.REDIS_HOST, port=6379, decode_responses=True):
        self.client = Redis(host=host, port=port, decode_responses=decode_responses)

    async def connect(self):
        try:
            await self.client.ping()
            log.info("Connected to Redis successfully.")
        except Exception as exc:
            log.critical(f"Failed to connect to Redis: {exc}")
            raise RuntimeError("Redis connection failed")

    async def close(self):
        await self.client.aclose()
