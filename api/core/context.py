import contextvars

# Context variables to store client information
# Context variables to store client information
APP_BUILD: contextvars.ContextVar[int | None] = contextvars.ContextVar("app_build", default=None)
APP_VERSION: contextvars.ContextVar[str | None] = contextvars.ContextVar("app_version", default=None)
PLATFORM: contextvars.ContextVar[str | None] = contextvars.ContextVar("platform", default=None)
DEVICE_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("device_id", default=None)
CLIENT_REGION: contextvars.ContextVar[str | None] = contextvars.ContextVar("client_region", default=None)
