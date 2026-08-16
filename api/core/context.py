import contextvars

# Context variables to store client information
APP_BUILD: contextvars.ContextVar[int] = contextvars.ContextVar("app_build", default=0)
APP_VERSION: contextvars.ContextVar[str] = contextvars.ContextVar("app_version", default="")
PLATFORM: contextvars.ContextVar[str] = contextvars.ContextVar("platform", default="")
DEVICE_ID: contextvars.ContextVar[str] = contextvars.ContextVar("device_id", default="")
CLIENT_REGION: contextvars.ContextVar[str | None] = contextvars.ContextVar("client_region", default="")
