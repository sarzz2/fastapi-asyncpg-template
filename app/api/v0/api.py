from fastapi import APIRouter

from .routers import users_route

api_router = APIRouter()

api_router.include_router(users_route.router, prefix="/users", tags=["users"])
