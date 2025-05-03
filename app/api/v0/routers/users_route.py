import logging
from datetime import timedelta
from typing import List
from uuid import uuid4

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from redis.asyncio import Redis
from starlette import status

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    create_sudo_token,
    verify_password,
    verify_token,
)
from app.core.config import settings
from app.core.dependencies import get_current_user, get_redis, get_sudo_user
from app.schemas.user import (
    PasswordChange,
    Session,
    TokenData,
    UserIn,
    UserLogin,
    UserModel,
)
from app.services.v0.user_service import (
    authenticate_user,
    create_user_session,
    get_sessions,
    get_user_password,
    register_user,
    revoke_user_session,
    search_user,
    update_user,
    update_user_password,
)

log = logging.getLogger("fastapi")

router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=TokenData)
async def register(request: Request, user: UserIn):
    """
    Register a new user
    """
    try:
        await register_user(user.id, user.username, user.email, user.password)
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    jti = str(uuid4())
    access_token = create_access_token(data={"sub": user.username, "id": str(user.id), "jti": jti})
    refresh_token = create_refresh_token(data={"sub": user.username, "id": str(user.id), "jti": jti})
    await create_user_session(
        user_id=user.id,
        jti=jti,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ip=request.client.host,
        user_agent=request.headers.get("user-agent", ""),
    )
    return {"access_token": access_token, "refresh_token": refresh_token}


@router.post("/login", response_model=TokenData)
async def login(user: UserLogin, request: Request):
    """
    Login a user
    """
    user = await authenticate_user(user.username, user.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    jti = str(uuid4())
    access_token = create_access_token(data={"sub": user.username, "id": str(user.id), "jti": jti})
    refresh_token = create_refresh_token(data={"sub": user.username, "id": str(user.id), "jti": jti})
    await create_user_session(
        user_id=str(user.id),
        jti=jti,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ip=request.client.host,
        user_agent=request.headers.get("user-agent", ""),
    )
    return {"access_token": access_token, "refresh_token": refresh_token}


@router.post("/token/refresh", response_model=TokenData)
async def validate_refresh_token(request: Request, refresh_token: str = Header(...)):
    """
    Endpoint to refresh access token
    """
    token_data = await verify_token(refresh_token, token_type="refresh")

    jti = str(uuid4())
    await create_user_session(
        token_data.id,
        jti,
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        request.client.host,
        request.headers.get("user-agent", ""),
    )
    return {
        "access_token": create_access_token(data={"sub": token_data.username, "id": str(token_data.id), "jti": jti}),
        "refresh_token": create_refresh_token(data={"sub": token_data.username, "id": str(token_data.id), "jti": jti}),
    }


@protected_router.post("/token/sudo")
async def get_sudo_token(user: UserLogin):
    """
    Endpoint to obtain a short-lived sudo token
    """
    user = await authenticate_user(user.username, user.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # Issue a sudo token with a short expiration
    sudo_token = create_sudo_token(data={"sub": user.username, "id": str(user.id)})
    return {"sudo_token": sudo_token}


@protected_router.get("/me", response_model=UserModel)
async def read_users_me(current_user: UserModel = Depends(get_current_user)):
    """
    Get current user
    """
    return current_user


@protected_router.get("/search/{query}", response_model=List[UserModel])
async def list_search_user(query: str):
    """
    Search for a user
    """
    users = await search_user(query)
    return users


@protected_router.patch("/update", response_model=UserModel)
async def update_current_user(request: Request, current_user: UserModel = Depends(get_current_user)):
    """
    Update user
    """
    update_data = await request.json()
    try:
        user = await update_user(current_user.id, **update_data)
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error(exc)
        raise HTTPException(status_code=500, detail="Internal Server Error")
    return user


@router.patch("/change_password")
async def change_user_password(
    change_password: PasswordChange,
    current_user: UserModel = Depends(get_sudo_user),
):
    # Verify the current password
    current_user_password = await get_user_password(current_user.id)
    if not verify_password(change_password.current_password, current_user_password.password):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    await update_user_password(change_password.new_password, current_user.id)

    return {"detail": "Password changed successfully."}


@protected_router.get("/sessions", response_model=List[Session])
async def list_sessions(
    current_user: UserModel = Depends(get_current_user),
):
    return await get_sessions(current_user.id)


@protected_router.delete("/sessions/{jti}")
async def revoke_session(
    jti: str,
    current_user: UserModel = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
):
    await revoke_user_session(current_user, jti, redis)
    return {"detail": "Session revoked"}


router.include_router(protected_router)
