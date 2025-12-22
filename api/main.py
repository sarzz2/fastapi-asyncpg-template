import time
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import AsyncGenerator, Awaitable, Callable, cast

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.responses import HTMLResponse, ORJSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from pyinstrument import Profiler
from secure import Secure
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from api.apps.api import api_router
from api.constants import Environments
from api.core.config import settings
from api.core.database import DataBase
from api.core.exception_handlers import register_exception_handlers
from api.core.i18n import I18nMiddleware
from api.core.logging_config import configure_logging
from api.core.rate_limit import limiter
from api.core.redis import redis_client
from api.middlewares.region_middleware import RegionASGIMiddleware
from api.schemas.health import DBRegionStatus, DBStatus, HealthResponse, RedisStatus
from migrate import check_all_migrations_applied

logger = configure_logging()


@asynccontextmanager
async def lifespan(
    app: FastAPI,  # pylint: disable=unused-argument,redefined-outer-name
) -> AsyncGenerator[None, None]:
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown events, including database and Redis connections,
    and migration checks.
    Args:
        app (FastAPI): The FastAPI application instance.
    Returns:
        None
    """
    database_instance = DataBase()
    await database_instance.create_pool(
        write_uri=settings.PRIMARY_DATABASE_URL,
        read_uris={"global": [settings.REPLICA_DATABASE_URL]},
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

# Initialize Rate Limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore
app.add_middleware(SlowAPIMiddleware)

register_exception_handlers(app)

Instrumentator().instrument(app).expose(app)


@app.get("/health", tags=["health"], response_model=HealthResponse)
@limiter.exempt
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    """
    db_health = await DataBase.health_check()
    redis_health = await redis_client.health_check()

    # Calculate DB status
    db_status_str = "up"
    total_healthy = sum(r["healthy_pools"] for r in db_health.values())
    total_pools = sum(r["total_pools"] for r in db_health.values())

    if total_healthy == 0 and total_pools > 0:
        db_status_str = "down"
    elif total_healthy < total_pools:
        db_status_str = "degraded"

    # Construct DB response
    db_regions = {
        region: DBRegionStatus(
            healthy_pools=stats["healthy_pools"],
            total_pools=stats["total_pools"],
            avg_latency=stats["avg_latency"],
        )
        for region, stats in db_health.items()
    }

    return HealthResponse(
        status="ok",
        database=DBStatus(status=db_status_str, regions=db_regions),
        redis=RedisStatus(status="up" if redis_health else "down"),
    )


@app.middleware("http")
async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """
    Middleware to log incoming HTTP requests and their processing time.
    Args:
        request (Request): The incoming HTTP request.
        call_next (Callable): The next middleware or route handler to call.
    Returns:
        Response: The HTTP response.
    """
    logger.info("\033[1;37m%s\033[0m , %s params: %s", request.method, request.url, dict(request.query_params))

    start_time = time.time()
    response: Response = await call_next(request)
    process_time = time.time() - start_time
    if response.status_code < 400:
        logger.info(
            "\033[1;37m Request completed with %s \033[0m %s in %.6fs",
            response.status_code,
            HTTPStatus(response.status_code).phrase,
            process_time,
        )
    else:
        logger.error(
            "Request failed with %s %s in %.6fs",
            response.status_code,
            HTTPStatus(response.status_code).phrase,
            process_time,
        )
    return response


@app.middleware("http")
async def profile_request(request: Request, call_next: Callable) -> Response:
    """
    Middleware to profile requests using pyinstrument.
    Activated by the 'profile=true' query parameter.
    """
    if request.query_params.get("profile"):
        profiler = Profiler(interval=0.001, async_mode="enabled")
        profiler.start()
        await call_next(request)
        profiler.stop()
        return HTMLResponse(profiler.output_html())

    return cast(Response, await call_next(request))


# Add CORS middleware to the FastAPI application
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1500, compresslevel=5)
app.add_middleware(RegionASGIMiddleware)
app.add_middleware(I18nMiddleware)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Explicit session cookie settings to make local OAuth flows more predictable.
# - `same_site='lax'` allows top-level GET navigations to include the cookie.
# - `https_only=False` is required for local HTTP development (localhost).
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
)

if settings.ENV in [Environments.PROD.value, Environments.STAGING.value]:
    app.add_middleware(HTTPSRedirectMiddleware)

# Security Headers
secure_headers = Secure.with_default_headers()


@app.middleware("http")
async def set_secure_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """
    Middleware to set security headers.
    """
    response = await call_next(request)
    await secure_headers.set_headers_async(response)  # type: ignore[arg-type]
    return response


app.include_router(api_router)


# Initialize Sentry
if settings.SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENV,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )
