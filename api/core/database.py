# pylint: disable=too-many-arguments
import asyncio
import json
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator, ClassVar, Dict, List, Literal, Optional, Type, TypeVar, Union, cast, overload

import asyncpg
from asyncpg import Connection, Pool, Record, create_pool
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from api.core.config import settings
from api.core.metrics import (
    DB_POOL_CONNECTIONS_IN_USE,
    DB_QUERY_DURATION_SECONDS,
    DB_QUERY_TOTAL,
    DB_SLOW_QUERIES_TOTAL,
)
from api.middlewares.region_middleware import CLIENT_REGION

BM = TypeVar("BM", bound="DataBase")
log = logging.getLogger("fastapi")


T = TypeVar("T", bound=BaseModel)

_clean_query_regex = re.compile(r"\s+")
_db_retry_strategy = retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.5),
    retry=retry_if_exception_type(
        (asyncpg.InterfaceError, asyncpg.CannotConnectNowError, asyncpg.ConnectionDoesNotExistError, OSError)
    ),
    reraise=True,
)


class CustomRecord(Record):
    """A custom record class that extends asyncpg.Record to provide Pydantic-style model access.
    This class allows:
    1. Dictionary-style access (record['field'])
    2. Attribute-style access (record.field)
    3. Fast conversion to Pydantic models using model_construct
    """

    def __getattr__(self, item: str) -> Any:
        """Attempt to get an attribute by first trying dictionary access, then falling back to normal attribute access.

        Args:
            item (str): The name of the attribute to retrieve

        Returns:
            Any: The value of the requested attribute

        Raises:
            AttributeError: If the attribute doesn't exist
        """
        try:
            return self[item]
        except KeyError:
            pass

        return super().__getattr__(item)

    def dict(self) -> Dict[str, Any]:
        """Convert record to a dictionary for Pydantic model construction.

        Returns:
            Dict[str, Any]: Dictionary representation of the record
        """
        return dict(self.items())


@dataclass
class PoolMeta:
    """Metadata container for database connection pools.

    This class holds information about a database connection pool including its URI,
    the pool object itself, associated region, health status, and latency metrics.

    Attributes:
        uri (str): The database connection URI
        pool (Pool): The asyncpg connection pool object
        region (str): The geographic region identifier for this pool
        healthy (bool): Flag indicating if the pool is currently healthy (default: True)
        last_latency (Optional[float]): The last measured latency in seconds for this pool (default: None)
    """

    uri: str
    pool: Pool
    region: str
    healthy: bool = True
    last_latency: Optional[float] = None


class DataBase(BaseModel):
    """A database management class that handles connection pools for read and write operations.

    This class provides functionality for managing multiple database connection pools across
    different regions, supporting read-write splitting, and automatic failover. It includes
    features like health checking, round-robin load balancing, and region-aware routing.

    Class Variables:
        write_pool (ClassVar[Optional[Pool]]): The primary write connection pool
        read_pools_by_region (ClassVar[Dict[str, List[PoolMeta]]]): Mapping of regions to their read pools
    # overall tasks
        _region_priority (ClassVar[List[str]]): Ordered list of region failover priorities
    """

    write_pool: ClassVar[Optional[Pool]] = None

    # maps region -> list[PoolMeta]
    read_pools_by_region: ClassVar[Dict[str, List[PoolMeta]]] = {}
    # overall tasks
    _health_task: ClassVar[Optional[asyncio.Task]] = None
    _region_priority: ClassVar[List[str]] = []

    @classmethod
    async def create_pool(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        cls,
        write_uri: str,
        read_uris: Optional[Dict[str, Union[str, List[str]]]] = None,
        min_con: int = settings.MIN_CONNECTION_COUNT,
        max_con: int = settings.MAX_CONNECTION_COUNT,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """Initialize database connection pools for both write and read operations.

        This method sets up the primary write pool and optional read replica pools across different regions.
        It also initializes health checking and connection management infrastructure.

        Args:
            write_uri (str): Connection URI for the primary (write) database
            read_uris (Dict[str, Union[str, List[str]]], optional): Mapping of regions to read replica URIs.
                Format: {"region": "uri"} or {"region": ["uri1", "uri2"]}
                If None, read operations will use the write pool.
            min_con (int, optional): Minimum number of connections per pool. Defaults to 1.
            max_con (int, optional): Maximum number of connections per pool. Defaults to 10.
            loop (asyncio.AbstractEventLoop, optional): Event loop to use for async operations.
                If None or 0, health checks are disabled.
        Raises:
            RuntimeError: If pool creation fails critically

        Note:
            - The method automatically configures JSON/JSONB type handling for all connections
            - Failed read replica pool creation is logged but doesn't stop overall initialization
            - If no read pools are created, the write pool is used for all operations
        """

        async def init_connection(connection: Connection) -> None:
            await connection.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
            await connection.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")

        # create write pool
        cls.write_pool = await create_pool(
            write_uri,
            min_size=min_con,
            max_size=max_con,
            loop=loop,
            record_class=CustomRecord,
            init=init_connection,
        )
        log.info("Established Write DB pool with %s - %s connections", min_con, max_con)

        # create pools per region
        cls.read_pools_by_region = {}
        if read_uris:
            for region, uris in read_uris.items():
                cls.read_pools_by_region.setdefault(region, [])
                for uri in uris:
                    try:
                        pool = await create_pool(
                            uri,
                            min_size=min_con,
                            max_size=max_con,
                            loop=loop,
                            record_class=CustomRecord,
                            init=init_connection,
                        )
                        cls.read_pools_by_region[region].append(PoolMeta(uri=uri, pool=pool, region=region))
                        log.info("Established Read DB pool for region=%s", region)
                    except (asyncpg.PostgresError, OSError) as e:
                        log.error("Failed to create read pool for %s (region=%s): %s; skipping.", uri, region, e)

        # fallback: if no read pools at all, use write pool under "global"
        if not cls.read_pools_by_region:
            cls.read_pools_by_region = {"global": [PoolMeta(uri=write_uri, pool=cls.write_pool, region="global")]}
            log.info("No read replicas configured — using write pool for reads (global).")

        # save region_priority on class so selection can use it
        cls._region_priority = list(settings.REGION_PRIORITY or list(cls.read_pools_by_region.keys()))

        if settings.HEALTH_CHECK_INTERVAL > 0:
            if cls._health_task and not cls._health_task.done():
                cls._health_task.cancel()
            cls._health_task = asyncio.create_task(cls._health_check_loop(interval=settings.HEALTH_CHECK_INTERVAL))

    @classmethod
    async def _health_check_loop(cls, interval: int) -> None:
        """Continuously monitor the health of all database connection pools.

        This internal method runs an infinite loop that periodically checks each pool's
        health by executing a simple query. It updates the health status and latency
        metrics for each pool.

        Args:
            interval (int): Time in seconds between health check cycles

        Note:
            - The method runs indefinitely until the task is cancelled
            - Each pool is checked independently; failure of one doesn't affect others
            - Health metrics are used by pool selection logic for failover and routing
            - Exceptions during health checks are logged but don't stop the loop
        """
        while True:
            await asyncio.sleep(interval)

            # Update connection pool gauges
            if cls.write_pool:
                DB_POOL_CONNECTIONS_IN_USE.labels(pool_type="write", region="global").set(
                    cls.write_pool.get_size() - cls.write_pool.get_free_size()
                )

            for region, metas in list(cls.read_pools_by_region.items()):
                total_in_use = 0
                for meta in metas:
                    if meta.pool:
                        total_in_use += meta.pool.get_size() - meta.pool.get_free_size()
                DB_POOL_CONNECTIONS_IN_USE.labels(pool_type="read", region=region).set(total_in_use)

                for meta in metas:
                    try:
                        t0 = time.perf_counter()
                        async with meta.pool.acquire() as conn:
                            await conn.fetchval("SELECT 1")
                        latency = time.perf_counter() - t0
                        meta.healthy = True
                        meta.last_latency = latency
                    except (asyncpg.PostgresError, OSError) as e:
                        meta.healthy = False
                        log.warning("Health check failed for %s: %s", meta.uri, e)
                    except asyncio.CancelledError:
                        log.info("Health check loop cancelled.")
                        raise

    @classmethod
    async def _choose_region(cls, client_region: Optional[str] = None) -> Optional[str]:
        """Select the most appropriate database region based on various criteria.

        This internal method implements the region selection strategy with the following
        priority order:
        1. Client's region if it has healthy pools
        2. Regions from cls._region_priority list
        3. Region with lowest average latency among healthy pools
        4. Any available region as last resort

        Args:
            client_region (Optional[str], default=None): The preferred region based on client location

        Returns:
            Optional[str]: The selected region name, or None if no suitable region is found

        Note:
            The selection logic prioritizes:
            - Proximity (matching client region)
            - Configured priorities (region_priority list)
            - Performance (lowest latency)
            - Availability (any working pool)
        """
        # exact match
        if client_region:
            if client_region in cls.read_pools_by_region:
                if any(m.healthy for m in cls.read_pools_by_region[client_region]):
                    log.debug("Region choice: client region match '%s'", client_region)
                    return client_region

        # region_priority fallback
        for r in cls._region_priority:
            metas = cls.read_pools_by_region.get(r)
            if metas and any(m.healthy for m in metas):
                log.debug("Region choice: priority list fallback '%s'", r)
                return r

        # pick by lowest avg latency
        best_region = None
        best_latency = None
        for r, metas in cls.read_pools_by_region.items():
            healthy = [m for m in metas if m.healthy and m.last_latency is not None]
            if not healthy:
                continue
            avg = sum(cast(float, m.last_latency) for m in healthy) / len(healthy)
            if best_latency is None or avg < best_latency:
                best_latency = avg
                best_region = r
        if best_region:
            log.debug("Region choice: lowest latency fallback '%s'", best_region)
            return best_region

        # last resort: any region with at least one pool
        for r, metas in cls.read_pools_by_region.items():
            if metas:
                log.debug("Region choice: last resort, first available '%s'", r)
                return r
        return None

    @classmethod
    def _get_region_for_pool(cls, pool_to_find: Pool) -> Optional[str]:
        """Find the region name associated with a given database pool.

        This internal method searches through all configured regions and their pools
        to find the region associated with a specific pool object.

        Args:
            pool_to_find (Pool): The pool object to locate

        Returns:
            Optional[str]: The region name if found, None if the pool isn't in any region

        Note:
            This is particularly useful when determining the region for the write pool
            when it's also configured as a read replica.
        """
        for region, metas in cls.read_pools_by_region.items():
            for meta in metas:
                if meta.pool is pool_to_find:
                    return region
        return None

    @classmethod
    async def _select_read_pool(cls, client_region: Optional[str] = None) -> tuple[Pool, str]:
        """Select an appropriate read pool based on client region and pool health status.

        This internal method implements the read pool selection strategy, considering:
        - Geographic proximity (client region)
        - Pool health status
        - Load balancing (round-robin within a region)
        - Fallback mechanisms for handling failures

        Args:
            client_region (Optional[str], default=None): The preferred region based on client location

        Returns:
            Tuple[Pool, str]: A tuple containing (selected pool object, region name)

        Raises:
            RuntimeError: If no pools are available (all pools are down and no fallback)

        Note:
            - Uses _choose_region() to select the appropriate region
            - Implements round-robin selection within a region
            - Includes fallback to write pool if no read pools are available
            - Maintains fairness using per-region locks for round-robin selection
        """
        region = await cls._choose_region(client_region=client_region)
        if region is None:
            if cls.write_pool:
                # Fallback to write pool, try to find its region if it's also a read replica
                region_name = cls._get_region_for_pool(cls.write_pool) or "primary_fallback"
                return cls.write_pool, region_name
            raise RuntimeError("No DB pools available")

        metas = cls.read_pools_by_region.get(region, [])
        healthy_metas = [m for m in metas if m.healthy]
        if not healthy_metas:
            # if no healthy in chosen region, fallback to any healthy pool globally
            all_healthy = []
            for ms in cls.read_pools_by_region.values():
                all_healthy.extend([m for m in ms if m.healthy])
            if all_healthy:
                metas = all_healthy
            else:
                # fallback to any configured pool (even unhealthy) to avoid total outage
                metas = [m for ms in cls.read_pools_by_region.values() for m in ms]

        # pick randomly from healthy pools to avoid lock contention under high load
        selected_meta = secrets.choice(metas)
        return selected_meta.pool, region

    @classmethod
    async def get_pool(cls, use_primary: bool = False) -> tuple[Pool, str]:
        """Get an appropriate database connection pool based on the operation type.

        This method selects either the primary write pool or an appropriate read pool
        based on the operation requirements and geographic routing rules.

        Args:
            use_primary (bool, default=False): If True, returns the write pool;
                if False, selects an appropriate read pool

        Returns:
            Tuple[Pool, str]: A tuple containing (selected pool object, region name)

        Raises:
            RuntimeError: If write pool is requested but not initialized, or if no
                suitable pool is available

        Note:
            - When use_primary is True, always returns the write pool
            - When use_primary is False, uses geographic routing and load balancing
              to select an appropriate read pool
        """
        if use_primary:
            if not cls.write_pool:
                raise RuntimeError("Write pool not initialized")
            # Try to find the region name if the write pool is also configured as a read replica
            region_name = cls._get_region_for_pool(cls.write_pool) or "primary"
            return cls.write_pool, region_name
        client_region = CLIENT_REGION.get()
        return await cls._select_read_pool(client_region=client_region)

    @classmethod
    @asynccontextmanager
    async def transaction(cls, use_primary: bool = True) -> AsyncGenerator[Connection, None]:
        """Context manager for database transactions."""
        pool, _ = await cls.get_pool(use_primary)
        async with pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    @staticmethod
    def clean_query(query: str) -> str:
        """Clean and normalize a SQL query string for logging purposes."""
        return _clean_query_regex.sub(" ", query.strip())

    @overload
    @classmethod
    async def fetch(
        cls: Type[BM],
        query: str,
        *args: Any,
        model: Type[T],
        fetch_row: Literal[True],
        timeout: float = settings.DB_TIMEOUT,
        log_explain: bool = False,
    ) -> Optional[T]: ...

    @overload
    @classmethod
    async def fetch(
        cls: Type[BM],
        query: str,
        *args: Any,
        model: Type[T],
        fetch_row: Literal[False],
        timeout: float = settings.DB_TIMEOUT,
        log_explain: bool = False,
    ) -> List[T]: ...

    @overload
    @classmethod
    async def fetch(
        cls: Type[BM],
        query: str,
        *args: Any,
        model: None = None,
        fetch_row: Literal[True] = ...,
        timeout: float = settings.DB_TIMEOUT,
        log_explain: bool = False,
    ) -> Optional[Record]: ...

    @overload
    @classmethod
    async def fetch(
        cls: Type[BM],
        query: str,
        *args: Any,
        model: None = None,
        fetch_row: Literal[False] = ...,
        timeout: float = settings.DB_TIMEOUT,
        log_explain: bool = False,
    ) -> List[Record]: ...

    @classmethod
    @_db_retry_strategy
    async def fetch(
        cls: Type[BM],
        query: str,
        *args: Any,
        model: Optional[Type[T]] = None,
        fetch_row: bool = False,
        timeout: float = settings.DB_TIMEOUT,
        log_explain: bool = False,
    ) -> Union[Optional[T], List[T], Optional[Record], List[Record]]:
        """Execute a read query using read replicas.

        Args:
            query: The SQL query to execute
            *args: Query parameters to bind
            model: The Pydantic model to convert the result(s) to.
            fetch_row: If True, fetch single row
            timeout: Query timeout in seconds
            log_explain: If True, log EXPLAIN output

        Returns:
            Model instance(s) or Record(s) based on parameters.
        """
        pool, region = await cls.get_pool(use_primary=False)

        if log_explain:
            try:
                explain_res = await pool.fetch(f"EXPLAIN {query}", *args, timeout=timeout)
                log.info("EXPLAIN %s: %s", cls.clean_query(query), explain_res)
            except Exception as e:  # pylint: disable=broad-except
                log.warning("Failed to EXPLAIN query: %s", e)

        start_time = time.perf_counter()
        if fetch_row:
            record = await pool.fetchrow(query, *args, timeout=timeout)
            duration = time.perf_counter() - start_time
            log.debug("Read query: %s args=%s dur=%.6fs, region=%s", cls.clean_query(query), args, duration, region)

            DB_QUERY_TOTAL.labels(type="read").inc()
            DB_QUERY_DURATION_SECONDS.labels(type="read").observe(duration)
            if duration > 1.0:
                DB_SLOW_QUERIES_TOTAL.labels(type="read").inc()

            return model.model_construct(**record.dict()) if model and record else record

        records = await pool.fetch(query, *args, timeout=timeout)
        duration = time.perf_counter() - start_time
        log.debug("Read query: %s args=%s dur=%.6fs, region=%s", cls.clean_query(query), args, duration, region)

        DB_QUERY_TOTAL.labels(type="read").inc()
        DB_QUERY_DURATION_SECONDS.labels(type="read").observe(duration)
        if duration > 1.0:
            DB_SLOW_QUERIES_TOTAL.labels(type="read").inc()

        return [model.model_construct(**r.dict()) for r in records] if model else records

    @overload
    @classmethod
    async def write(
        cls: Type[BM],
        query: str,
        *args: Any,
        model: Type[T],
        timeout: float = settings.DB_TIMEOUT,
    ) -> T: ...

    @overload
    @classmethod
    async def write(
        cls: Type[BM],
        query: str,
        *args: Any,
        model: None = None,
        timeout: float = settings.DB_TIMEOUT,
    ) -> Record: ...

    @classmethod
    @_db_retry_strategy
    async def write(
        cls: Type[BM],
        query: str,
        *args: Any,
        model: Optional[Type[T]] = None,
        timeout: float = settings.DB_TIMEOUT,
    ) -> Union[T, Record]:
        """Execute a write query using primary pool with results.

        Args:
            query: The SQL query to execute
            args: Query parameters to bind
            model: The Pydantic model to convert the result to.
            timeout: Query timeout in seconds

        Returns:
            Model instance or Record if successful, None if results.
        """
        pool, _ = await cls.get_pool(use_primary=True)
        start_time = time.perf_counter()
        record = await pool.fetchrow(query, *args, timeout=timeout)
        duration = time.perf_counter() - start_time
        log.debug("Write query: %s args=%s dur=%.6fs", cls.clean_query(query), args, duration)

        DB_QUERY_TOTAL.labels(type="write").inc()
        DB_QUERY_DURATION_SECONDS.labels(type="write").observe(duration)
        if duration > 1.0:
            DB_SLOW_QUERIES_TOTAL.labels(type="write").inc()

        if record:
            return model.model_construct(**record.dict()) if model else record
        return None

    @classmethod
    @_db_retry_strategy
    async def fetchval(
        cls,
        query: str,
        *args: Any,
        con: Optional[Union[Connection, Pool]] = None,
        column: int = 0,
        use_primary: bool = False,
        timeout: float = settings.DB_TIMEOUT,
    ) -> Any:
        """Execute a query and return a single value.

        This method executes a SQL query and returns a single value from the first row.
        Useful for queries that return a single value like COUNT(*) or MAX(column).

        Args:
            query: The SQL query to execute
            *args: Query parameters to bind
            con (Union[Connection, Pool], optional): Specific connection or pool to use.
                If None, an appropriate pool will be selected.
            column (int, default=0): Zero-based index of the column to return
            use_primary (bool, default=False): If True, forces use of write pool
            timeout (float): Query timeout in seconds

        Returns:
            Any: The value from the specified column of the first row, or None if no rows

        Note:
            - Returns None if no rows match the query
            - Only returns the value of a single column
            - Automatically handles pool selection if no connection provided
            - Logs query execution details including duration and region
        """
        region = None
        if con is None:
            con, region = await cls.get_pool(use_primary=use_primary)

        start_time = time.perf_counter()
        value = await con.fetchval(query, *args, column=column, timeout=timeout)
        duration = time.perf_counter() - start_time
        log.debug("Running query: %s args=%s dur=%.6fs, region=%s", cls.clean_query(query), args, duration, region)
        return value

    @classmethod
    @_db_retry_strategy
    async def execute(
        cls,
        query: str,
        *args: Any,
        con: Optional[Union[Connection, Pool]] = None,
        timeout: float = settings.DB_TIMEOUT,
    ) -> str:
        """Execute a query that modifies the database.

        This method executes a SQL query that modifies the database (INSERT, UPDATE,
        DELETE, etc.) and returns the command completion tag.

        Args:
            query (str): The SQL query to execute
            args: Query parameters to bind
            con: Specific connection or pool to use. If None, the primary write pool will be used.
            timeout (float): Query timeout in seconds

        Returns:
            str: The command completion tag (e.g., "INSERT 0 1")

        Raises:
            RuntimeError: If no write pool is available

        Note:
            - Always uses the write pool if no specific connection is provided
            - Suitable for queries that modify the database
            - Logs query execution details including duration
            - Returns a string indicating the operation result
        """
        if con is None:
            if cls.write_pool is None:
                raise RuntimeError("No write pool available")
            con = cls.write_pool

        start_time = time.perf_counter()
        result = await con.execute(query, *args, timeout=timeout)
        duration = time.perf_counter() - start_time
        log.debug("Running query: %s args=%s dur=%.6fs", cls.clean_query(query), args, duration)
        return str(result)

    @classmethod
    async def close_pool(cls) -> None:
        """Clean up and close all database connection pools.

        This method performs a graceful shutdown of all database connections by:
        1. Cancelling the health check task if running
        2. Closing all read replica pools
        3. Closing the primary write pool
        4. Resetting the pool tracking variables

        Returns:
            None

        Note:
            - Should be called during application shutdown
            - Attempts to close all pools even if some fail
            - Logs any errors during closure
            - Resets all pool-related class variables
        """
        if cls._health_task and not cls._health_task.done():
            cls._health_task.cancel()
        # close all pools
        for metas in cls.read_pools_by_region.values():
            for m in metas:
                try:
                    if m.pool and not getattr(m.pool, "_closed", False):
                        await asyncio.wait_for(m.pool.close(), timeout=5.0)
                except (asyncpg.PostgresError, asyncio.TimeoutError) as e:
                    log.error("Error closing read pool for %s: %s", m.uri, e)
        if cls.write_pool and not getattr(cls.write_pool, "_closed", False):
            try:
                await asyncio.wait_for(cls.write_pool.close(), timeout=5.0)
            except (asyncpg.PostgresError, asyncio.TimeoutError) as e:
                log.error("Error closing write pool: %s", e)
        cls.read_pools_by_region = {}
        cls.write_pool = None
        log.info("Closed DB connection pools")

    @classmethod
    async def health_check(cls) -> Dict[str, Dict[str, Any]]:
        """
        Get health status of all database pools.
        Returns:
            Dict[str, Dict[str, Any]]: A dictionary mapping region names to their health status,
            including number of healthy pools, total pools, and average latency.
        """
        results = {}
        for region, metas in cls.read_pools_by_region.items():
            results[region] = {
                "healthy_pools": sum(1 for m in metas if m.healthy),
                "total_pools": len(metas),
                "avg_latency": (
                    sum(m.last_latency for m in metas if m.healthy and m.last_latency is not None)
                    / sum(1 for m in metas if m.healthy and m.last_latency is not None)
                    if any(m.healthy and m.last_latency is not None for m in metas)
                    else None
                ),
            }
        return results

    @classmethod
    async def get_pool_stats(cls) -> Dict[str, Any]:
        """
        Get current statistics for all pools.
        Returns:
            Dict[str, Any]: A dictionary containing statistics for write and read pools.
        Raises:
            RuntimeError: If database is not initialized
        """
        if not cls.write_pool:
            raise RuntimeError("Database not initialized")

        stats: Dict[str, Any] = {
            "write_pool": {
                "size": cls.write_pool.get_size(),
                "free_size": cls.write_pool.get_free_size(),
                "usage": cls.write_pool.get_usage(),
            },
            "read_pools": {},
        }

        for region, metas in cls.read_pools_by_region.items():
            stats["read_pools"][region] = [
                {
                    "healthy": meta.healthy,
                    "last_latency": meta.last_latency,
                    "size": meta.pool.get_size(),
                    "free_size": meta.pool.get_free_size(),
                    "usage": meta.pool.get_usage(),
                }
                for meta in metas
            ]
        return stats


async def get_db() -> AsyncGenerator[Type[DataBase], None]:
    """FastAPI dependency for database access.

    Returns:
        AsyncGenerator[Type[DataBase], None]: The DataBase class for dependency injection
    """
    yield DataBase
