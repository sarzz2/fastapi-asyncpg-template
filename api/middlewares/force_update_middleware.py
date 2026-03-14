import logging

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from api.apps.user.v0.dao.version import VersionDAO
from api.apps.user.v0.service.version import VersionService
from api.core.context import APP_BUILD, PLATFORM
from api.core.database import DataBase

logger = logging.getLogger("fastapi")


class ForceUpdateMiddleware(BaseHTTPMiddleware):
    """
    Middleware to check if the client app version is supported.
    """

    def __init__(self, app: ASGIApp, skip_paths: list[str] = None):
        super().__init__(app)
        # Exclude health, docs, and the explicit version check endpoint
        self.skip_paths = skip_paths or ["/health", "/docs", "/redoc", "/openapi.json", "/api/v0/app/check"]
        # Pre-instantiate service (DataBase is a singleton-like class with classmethods)
        self.version_service = VersionService(version_dao=VersionDAO(db=DataBase))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip paths that don't need version checking
        if any(request.url.path.startswith(path) for path in self.skip_paths):
            return await call_next(request)

        # Get info from context (already set by ClientInfoMiddleware)
        platform = PLATFORM.get()
        app_build = APP_BUILD.get()

        if platform and app_build is not None:
            update_info = await self.version_service.check_force_update(platform, app_build)

            if update_info and update_info.force:
                logger.warning(
                    "Force update required: platform=%s, build=%s, min_build=%s",
                    platform,
                    app_build,
                    update_info.min_build,
                )
                return JSONResponse(status_code=426, content=update_info.model_dump())

        return await call_next(request)
