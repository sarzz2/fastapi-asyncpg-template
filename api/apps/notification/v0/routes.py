import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from api.apps.notification.v0.schemas import DeviceRegisterRequest, DeviceResponse
from api.apps.notification.v0.service import NotificationService, get_notification_service
from api.apps.user.v0.dao.user import UserDAO, get_user_dao
from api.apps.user.v0.schemas.user import UserData
from api.core.auth import verify_token
from api.core.dependencies import get_current_user
from api.core.redis import get_redis

router = APIRouter()
logger = logging.getLogger("fastapi")


@router.get("/sse")
async def sse_notifications(
    request: Request,
    token: str = Query(..., description="JWT access token for authentication"),
    user_dao: UserDAO = Depends(get_user_dao),
    redis: Redis = Depends(get_redis),
    service: NotificationService = Depends(get_notification_service),
) -> StreamingResponse:
    """
    Server-Sent Events (SSE) endpoint for real-time personal and broadcast notifications.
    Native auto-reconnection and proxy-friendly over standard HTTP.
    """
    token_data = await verify_token(token, redis)
    if not token_data.id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await user_dao.get_by_id(token_data.id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or non-existent user")

    return StreamingResponse(
        service.stream_sse(request, user.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/devices", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    payload: DeviceRegisterRequest,
    current_user: UserData = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> DeviceResponse:
    """
    Register or update an FCM push notification token for a user device.
    """
    return await service.register_device(
        user_id=current_user.id,
        fcm_token=payload.fcm_token,
        platform=payload.platform,
        device_name=payload.device_name,
    )


@router.delete("/devices/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_device(
    token: str,
    current_user: UserData = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> None:
    """
    Unregister an FCM push notification token (e.g. upon user logout).
    """
    await service.unregister_device(user_id=current_user.id, fcm_token=token)


@router.get("/devices", response_model=list[DeviceResponse])
async def list_devices(
    current_user: UserData = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> list[DeviceResponse]:
    """
    List all registered active push notification devices for current user.
    """
    return await service.get_user_devices(current_user.id)
