from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from api.core.config import settings


def get_real_user_key(request: Request) -> str:
    """
    Identify the user for rate limiting.
    Priority:
    1. Authorization Header (for API clients)
    2. IP Address (fallback for unauthenticated)

    This ensures that multiple authenticated users behind the same NAT
    (Organization Network) are not blocked by each other's traffic.
    """
    # 1. Authorization Header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header

    # 2. Fallback to IP
    return str(get_remote_address(request))


# Initialize the limiter
# - key_func: determines how to identify distinct users
# - default_limits: applies to all routes unless overridden
# - enabled: disabled in 'test' environment to allow pytest to run freely
limiter = Limiter(key_func=get_real_user_key, default_limits=["100/minute"], enabled=settings.ENV != "test")
