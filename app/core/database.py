import asyncio
import logging
import re
import time
from typing import ClassVar, List, Type, TypeVar, Union

from asyncpg import Connection, Pool, Record, connect, create_pool
from pydantic import BaseModel

BM = TypeVar("BM", bound="Model")
log = logging.getLogger("fastapi")


class CustomRecord(Record):
    def __getattr__(self, item: str):
        try:
            return self[item]
        except KeyError:
            pass

        return super().__getattr__(item)


class DataBase(BaseModel):
    pool: ClassVar[Pool] = None

    @classmethod
    async def create_pool(
        cls,
        uri: str,
        *,
        min_con: int = 1,
        max_con: int = 10,
        loop: asyncio.AbstractEventLoop = None,
        **kwargs,
    ) -> None:
        cls.pool = await create_pool(
            uri,
            min_size=min_con,
            max_size=max_con,
            loop=loop,
            record_class=CustomRecord,
            **kwargs,
        )
        log.info(f"Established DB pool with {min_con} - {max_con} connections")

    @classmethod
    async def create_connection(cls, uri: str, **kwargs) -> Connection:
        return await connect(uri, **kwargs)

    @staticmethod
    def clean_query(query: str) -> str:
        # Remove leading/trailing spaces and replace multiple spaces/newlines with a single space
        return re.sub(r"\s+", " ", query.strip())

    @classmethod
    async def fetch(
        cls: Type[BM],
        query,
        *args,
        con: Union[Connection, Pool] = None,
        convert: bool = True,
    ) -> Union[List[BM], List[Record]]:
        if con is None:
            con = cls.pool
        start_time = time.perf_counter()
        records = await con.fetch(query, *args)
        duration = time.perf_counter() - start_time
        cleaned_query = cls.clean_query(query)
        log.debug(f"Running query: {cleaned_query} with args: {args} ({duration:.6f} seconds)")
        if cls is DataBase or convert is False:
            return records
        return [cls(**record) for record in records]

    @classmethod
    async def fetchrow(
        cls: Type[BM],
        query,
        *args,
        con: Union[Connection, Pool] = None,
        convert: bool = True,
    ) -> Union[BM, Record, None]:
        con = con or cls.pool
        start_time = time.perf_counter()
        async with con.acquire() as connection:
            record = await connection.fetchrow(query, *args)
        duration = time.perf_counter() - start_time
        cleaned_query = cls.clean_query(query)
        log.debug(f"Running query: {cleaned_query} with args: {args} ({duration:.6f} seconds)")
        if cls is DataBase or record is None or convert is False:
            return record
        return cls(**record)

    @classmethod
    async def fetchval(cls, query, *args, con: Union[Connection, Pool] = None, column: int = 0):
        if con is None:
            con = cls.pool
        start_time = time.perf_counter()
        result = await con.fetchval(query, *args, column=column)
        duration = time.perf_counter() - start_time
        cleaned_query = cls.clean_query(query)
        log.info(f"Running query: {cleaned_query} with args: {args} ({duration:.6f} seconds)")
        return result

    @classmethod
    async def execute(cls, query: str, *args, con: Union[Connection, Pool] = None) -> str:
        if con is None:
            con = cls.pool
        start_time = time.perf_counter()
        result = await con.execute(query, *args)
        duration = time.perf_counter() - start_time
        cleaned_query = cls.clean_query(query)
        log.debug(f"Running query: {cleaned_query} with args: {args} ({duration:.6f} seconds)")
        return result

    @classmethod
    async def close_pool(cls) -> None:
        if cls.pool is not None:
            await cls.pool.close()
            cls.pool = None
            log.info("Closed the database connection pool\n")
