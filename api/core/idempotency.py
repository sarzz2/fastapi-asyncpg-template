import json
from typing import Any, Callable, Coroutine

from fastapi import HTTPException, Request, Response, status
from fastapi.routing import APIRoute

from api.constants import IDEMPOTENCY_TTL
from api.core.redis import get_redis
from api.shared.redis_keys import RedisKeys


class IdempotencyManager:
    """Manages idempotency operations for API requests."""

    @staticmethod
    async def get_key(request: Request) -> str | None:
        """Get the idempotency key from the request headers."""
        return request.headers.get("Idempotency-Key")

    @staticmethod
    async def acquire_lock(key: str) -> bool:
        """Acquire an exclusive lock for the given key."""
        redis = await get_redis()
        # SETNX returns True if key was set, False if it already exists
        lock_key = RedisKeys.IDEMPOTENCY_LOCK.format(key=key)
        acquired = await redis.set(lock_key, "in-progress", ex=IDEMPOTENCY_TTL, nx=True)
        return bool(acquired)

    @staticmethod
    async def get_cached_response(key: str) -> Response | None:
        """Retrieve a cached response for the given idempotency key."""
        redis = await get_redis()
        response_key = RedisKeys.IDEMPOTENCY_RESPONSE.format(key=key)
        cached_data = await redis.get(response_key)
        if cached_data:
            data = json.loads(cached_data)
            return Response(
                content=data["content"],
                status_code=data["status_code"],
                headers=data["headers"],
                media_type=data.get("media_type"),
            )
        return None

    @staticmethod
    async def cache_response(key: str, response: Response) -> None:
        """Cache a response for the given idempotency key."""
        redis = await get_redis()
        # We only cache if we have body content we can read.
        # StreamingResponses are harder, but typical JSON responses are fine.
        content: bytes | memoryview = b""
        if hasattr(response, "body"):
            content = response.body

        content_bytes = content.tobytes() if isinstance(content, memoryview) else content

        data = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content": content_bytes.decode("utf-8") if isinstance(content_bytes, bytes) else content_bytes,
            "media_type": response.media_type,
        }

        response_key = RedisKeys.IDEMPOTENCY_RESPONSE.format(key=key)
        await redis.set(response_key, json.dumps(data), ex=IDEMPOTENCY_TTL)


class IdempotentRoute(APIRoute):
    """
    A custom APIRoute that handles idempotency.
    It checks for the `Idempotency-Key` header. If missing, acts normally.
    If present, it ensures the request is processed exactly once.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            idempotency_key = await IdempotencyManager.get_key(request)

            # If no idempotency key is provided, just run normally
            if not idempotency_key:
                return await original_route_handler(request)

            # Check if we already have a cached response
            cached_response = await IdempotencyManager.get_cached_response(idempotency_key)
            if cached_response:
                return cached_response

            # Try to acquire lock
            lock_acquired = await IdempotencyManager.acquire_lock(idempotency_key)
            if not lock_acquired:
                # If we couldn't acquire the lock and there is no cached response,
                # it means the request is currently being processed.
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A request with this Idempotency-Key is currently being processed.",
                )

            # Process the original request
            response = await original_route_handler(request)

            # Cache the response
            # Only cache successful responses and deterministic errors (like 400 Bad Request)
            if 200 <= response.status_code < 500:
                await IdempotencyManager.cache_response(idempotency_key, response)

            return response

        return custom_route_handler
