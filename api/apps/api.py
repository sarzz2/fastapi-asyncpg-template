from fastapi import APIRouter

from api.apps.s3.v0.routes.s3 import router as s3_v0_router
from api.apps.user.v0.routes.auth import router as auth_v0_router
from api.apps.user.v0.routes.role import router as role_v0_router
from api.apps.user.v0.routes.user import router as user_v0_router
from api.core.config import settings

api_router = APIRouter()
api_router.include_router(auth_v0_router, prefix=f"{settings.API_V0_STR}/auth", tags=["Auth"])
api_router.include_router(user_v0_router, prefix=f"{settings.API_V0_STR}/users", tags=["Users"])

api_router.include_router(s3_v0_router, prefix=f"{settings.API_V0_STR}/s3", tags=["S3"])
api_router.include_router(role_v0_router, prefix=f"{settings.API_V0_STR}/roles", tags=["Roles"])
