import functools
import inspect
import json
import logging
import time
from typing import Any, Awaitable, Callable, List, Optional, ParamSpec, Type, TypeVar, Union

from pydantic import BaseModel

from api.core.metrics import (
    CACHE_HIT_MISS_TOTAL,
    CACHE_OPERATION_DURATION_SECONDS,
    CACHE_REQUESTS_TOTAL,
    REDIS_ERRORS_TOTAL,
)
from api.core.redis import redis_client

log = logging.getLogger("fastapi")

# Pre-bind metrics for performance
CACHE_GET_REQUESTS = CACHE_REQUESTS_TOTAL.labels(operation="get")
CACHE_SET_REQUESTS = CACHE_REQUESTS_TOTAL.labels(operation="set")
CACHE_GET_DURATION = CACHE_OPERATION_DURATION_SECONDS.labels(operation="get")
CACHE_SET_DURATION = CACHE_OPERATION_DURATION_SECONDS.labels(operation="set")
CACHE_HIT = CACHE_HIT_MISS_TOTAL.labels(result="hit")
CACHE_MISS = CACHE_HIT_MISS_TOTAL.labels(result="miss")
REDIS_GET_ERRORS = REDIS_ERRORS_TOTAL.labels(operation="get")
REDIS_SET_ERRORS = REDIS_ERRORS_TOTAL.labels(operation="set")

T = TypeVar("T")
P = ParamSpec("P")
R = TypeVar("R")


def _generate_key(pattern: str, func: Callable, args: tuple, kwargs: dict) -> str:
    """Helper to generate a key from a pattern and function arguments."""
    sig = inspect.signature(func)
    bound_args = sig.bind(*args, **kwargs)
    bound_args.apply_defaults()
    try:
        return pattern.format(**bound_args.arguments)
    except KeyError as e:
        raise ValueError(f"Failed to generate cache key for pattern '{pattern}'") from e


async def _get_from_cache(key: str, hash_key: Optional[str], model: Optional[Type[BaseModel]]) -> Optional[Any]:
    """Helper to retrieve and deserialize data from Redis."""

    start = time.perf_counter()
    try:
        CACHE_GET_REQUESTS.inc()
        if hash_key:
            cached_value = await redis_client.client.hget(hash_key, key)
        else:
            cached_value = await redis_client.client.get(key)

        duration = time.perf_counter() - start
        CACHE_GET_DURATION.observe(duration)

        if cached_value:
            CACHE_HIT.inc()
            log.debug("Cache hit for key: %s%s", f"[{hash_key}] " if hash_key else "", key)
            data = json.loads(cached_value)
            if model:
                if isinstance(data, list):
                    return [model.model_validate(item) for item in data]
                return model.model_validate(data)
            return data

        CACHE_MISS.inc()
    except Exception as e:  # pylint: disable=broad-except
        REDIS_GET_ERRORS.inc()
        log.warning("Error reading from cache for key %s: %s", key, e)
    return None


async def _save_to_cache(key: str, hash_key: Optional[str], value: Any, expire: Optional[int]) -> None:
    """Helper to serialize and save data to Redis."""
    start = time.perf_counter()
    try:
        CACHE_SET_REQUESTS.inc()
        if value is not None:
            if isinstance(value, list):
                serialized_data = json.dumps(
                    [item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value]
                )
            elif isinstance(value, BaseModel):
                serialized_data = value.model_dump_json()
            else:
                serialized_data = json.dumps(value)

            if hash_key:
                async with redis_client.client.pipeline() as pipe:
                    pipe.hset(hash_key, key, serialized_data)
                    if expire:
                        pipe.expire(hash_key, expire)
                    await pipe.execute()
            else:
                if expire:
                    await redis_client.client.set(key, serialized_data, ex=expire)
                else:
                    await redis_client.client.set(key, serialized_data)

            log.debug(
                "Cache set for key: %s%s (expire=%s)",
                f"[{hash_key}] " if hash_key else "",
                key,
                expire if expire else "No Expiry",
            )

            duration = time.perf_counter() - start
            CACHE_SET_DURATION.observe(duration)
    except Exception as e:  # pylint: disable=broad-except
        REDIS_SET_ERRORS.inc()
        log.warning("Error writing to cache for key %s: %s", key, e)


def cache(
    key_pattern: str,
    hash_key: Optional[str] = None,
    expire: Optional[int] = 3600,
    model: Optional[Type[BaseModel]] = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """
    Decorator to cache the result of a function in Redis.

    Args:
        key_pattern: The Redis key pattern (or field pattern if hash_key is used).
        hash_key: Optional. If provided, uses a Redis Hash with this key.
        expire: Expiration time in seconds. Defaults to 3600 (1 hour).
            If None, the key will not expire.
        model: Optional Pydantic model to deserialize the result.
    Returns:
        Callable: The decorated function.
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # 1. Construct the Redis key (or field)
            try:
                key = _generate_key(key_pattern, func, args, kwargs)
            except ValueError as e:
                log.error(str(e))
                return await func(*args, **kwargs)

            # 2. Try to get from Redis
            cached_result = await _get_from_cache(key, hash_key, model)
            if cached_result is not None:
                return cached_result  # type: ignore

            # 3. If not found, call the function
            result = await func(*args, **kwargs)

            # 4. Store in Redis
            await _save_to_cache(key, hash_key, result, expire)

            return result

        return wrapper

    return decorator


def cache_invalidate(
    key_pattern: Union[str, List[str]],
    hash_key: Optional[str] = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """
    Decorator to invalidate cache keys after function execution.

    Args:
        key_pattern: The Redis key pattern(s) to delete. Can be a single string or list.
        hash_key: Optional. If provided, deletes fields from this Hash.
    Returns:
        Callable: The decorated function.
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # 1. Execute the function first
            result = await func(*args, **kwargs)

            # 2. Invalidate Cache
            try:
                patterns = [key_pattern] if isinstance(key_pattern, str) else key_pattern

                keys_to_delete = []
                for pattern in patterns:
                    try:
                        k = _generate_key(pattern, func, args, kwargs)
                        keys_to_delete.append(k)
                    except ValueError as e:
                        log.error(str(e))

                if keys_to_delete:
                    if hash_key:
                        await redis_client.client.hdel(hash_key, *keys_to_delete)
                        log.debug("Invalidated hash fields %s in %s", keys_to_delete, hash_key)
                    else:
                        await redis_client.client.delete(*keys_to_delete)
                        log.debug("Invalidated keys %s", keys_to_delete)

            except Exception as e:  # pylint: disable=broad-except
                log.warning("Error invalidating cache: %s", e)

            return result

        return wrapper

    return decorator
