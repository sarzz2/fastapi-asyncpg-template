import time
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import AsyncGenerator, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.responses import ORJSONResponse

from api.apps.api import api_router
from api.constants import Environments
from api.core.config import settings
from api.core.database import DataBase
from api.core.dependencies import redis_client
from api.core.exception_handlers import register_exception_handlers
from api.core.logging_config import configure_logging
from migrate import check_all_migrations_applied

logger = configure_logging()


@asynccontextmanager
async def lifespan(
    app: FastAPI,  # pylint: disable=unused-argument
) -> AsyncGenerator[None, None]:
    database_instance = DataBase()
    await database_instance.create_pool(
        write_uri=settings.PRIMARY_DATABASE_URL,
        read_uris={"global": [settings.REPLICA_DATABASE_URL]},
        health_check_interval=3600,
    )
    logger.info("Database connected successfully")
    await redis_client.connect()
    all_migrations_applied_check = await check_all_migrations_applied()
    if not all_migrations_applied_check:
        logger.critical("You have pending migrations")
        raise RuntimeError("You have pending migrations")
    yield
    await database_instance.close_pool()
    await redis_client.close()
    logger.info("Database disconnected successfully")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
)

register_exception_handlers(app)


@app.middleware("http")
async def log_requests(request: Request, call_next: Callable) -> Response:
    logger.info(f"\033[1;37m{request.method}\033[0m , {request.url} params: {dict(request.query_params)}")

    start_time = time.time()
    response: Response = await call_next(request)
    process_time = time.time() - start_time
    if response.status_code < 400:
        logger.info(
            f"\033[1;37m Request completed with {response.status_code} \033[0m"
            f" {HTTPStatus(response.status_code).phrase} in {process_time:.6f}s"
        )
    else:
        logger.error(
            f"Request failed with {response.status_code}"
            f" {HTTPStatus(response.status_code).phrase} in {process_time:.6f}s"
        )
    return response


app.include_router(api_router)
origins = ["http://localhost:3000", "http://localhost:3001", "http://localhost:5173"]

# Add CORS middleware to the FastAPI application
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1500, compresslevel=5)
# app.add_middleware(RegionASGIMiddleware)

if settings.ENV in [Environments.PROD.value, Environments.STAGING.value]:
    app.add_middleware(HTTPSRedirectMiddleware)
