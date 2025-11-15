from fastapi import APIRouter

from api.apps.user.v0.routes.auth import router as auth_v0_router
from api.apps.user.v0.routes.user import router as user_v0_router
from api.core.config import settings

api_router = APIRouter()
api_router.include_router(auth_v0_router, prefix=f"{settings.API_V0_STR}/auth", tags=["auth"])
api_router.include_router(user_v0_router, prefix=f"{settings.API_V0_STR}/users", tags=["users"])
