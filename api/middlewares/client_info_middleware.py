import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from api.constants import RequestHeaders
from api.core.context import APP_BUILD, APP_VERSION, DEVICE_ID, PLATFORM

logger = logging.getLogger("fastapi")


class ClientInfoMiddleware(BaseHTTPMiddleware):
    """
    Middleware to extract client information from request headers and store it in context variables.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        app_version = request.headers.get(RequestHeaders.APP_VERSION.value)
        app_build_raw = request.headers.get(RequestHeaders.APP_BUILD.value)
        platform = request.headers.get(RequestHeaders.PLATFORM.value)
        device_id = request.headers.get(RequestHeaders.DEVICE_ID.value)

        app_build = None
        if app_build_raw:
            try:
                app_build = int(app_build_raw)
            except ValueError:
                logger.debug("Failed to parse app_build integer from header value: %s", app_build_raw)

        # Set context variables
        av_token = APP_VERSION.set(app_version)
        ab_token = APP_BUILD.set(app_build)
        p_token = PLATFORM.set(platform)
        di_token = DEVICE_ID.set(device_id)

        if app_version or platform or device_id:
            logger.debug(
                "Client info context set: platform=%s, app_version=%s, app_build=%s, device_id=%s",
                platform,
                app_version,
                app_build,
                device_id,
            )

        try:
            response = await call_next(request)

            # Optionally add these to response headers for debugging
            if app_build:
                response.headers["X-Server-Processed-Build"] = str(app_build)

            return response
        finally:
            # Reset context variables
            APP_VERSION.reset(av_token)
            APP_BUILD.reset(ab_token)
            PLATFORM.reset(p_token)
            DEVICE_ID.reset(di_token)
