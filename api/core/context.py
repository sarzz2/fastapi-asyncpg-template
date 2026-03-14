import contextvars
from typing import Optional

# Context variables to store client information
# Context variables to store client information
APP_BUILD: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("app_build", default=None)
APP_VERSION: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("app_version", default=None)
PLATFORM: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("platform", default=None)
DEVICE_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("device_id", default=None)
CLIENT_REGION: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("client_region", default=None)
