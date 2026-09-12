from fastapi import APIRouter

from api.apps.common.v0.routes.dead_letter_task import router as dead_letter_task_v0_router
from api.apps.common.v0.routes.periodic_task import router as periodic_task_v0_router
from api.apps.common.v0.routes.s3 import router as s3_v0_router
from api.apps.notification.v0.routes import router as notification_router
from api.apps.user.v0.routes.auth import router as auth_v0_router
from api.apps.user.v0.routes.role import router as role_v0_router
from api.apps.user.v0.routes.user import router as user_v0_router
from api.apps.user.v0.routes.version import router as version_v0_router
from api.core.config import settings

api_router = APIRouter()
api_router.include_router(auth_v0_router, prefix=f"{settings.API_V0_STR}/auth", tags=["Auth"])
api_router.include_router(user_v0_router, prefix=f"{settings.API_V0_STR}/users", tags=["Users"])

api_router.include_router(s3_v0_router, prefix=f"{settings.API_V0_STR}/s3", tags=["S3"])
api_router.include_router(
    periodic_task_v0_router, prefix=f"{settings.API_V0_STR}/common/periodic-tasks", tags=["Periodic Tasks"]
)
api_router.include_router(
    dead_letter_task_v0_router, prefix=f"{settings.API_V0_STR}/common/dlq", tags=["Dead Letter Queue"]
)
api_router.include_router(role_v0_router, prefix=f"{settings.API_V0_STR}/roles", tags=["Roles"])
api_router.include_router(notification_router, prefix=f"{settings.API_V0_STR}/notifications", tags=["Notifications"])
api_router.include_router(version_v0_router, prefix=f"{settings.API_V0_STR}/app", tags=["App Version"])
