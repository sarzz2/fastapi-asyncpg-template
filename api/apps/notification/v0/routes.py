from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis

from api.apps.notification.v0.channels.websocket import connection_manager
from api.apps.user.v0.dao.user import UserDAO, get_user_dao
from api.core.auth import verify_token
from api.core.redis import get_redis

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    user_dao: UserDAO = Depends(get_user_dao),
    redis: Redis = Depends(get_redis),
) -> None:
    """
    WebSocket endpoint for real-time notifications.
    Authenticate user via JWT token in query param.
    """
    try:
        # Verify Token
        token_data = await verify_token(token, redis)
        if not token_data.id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        user_id = token_data.id

        # Check if user exists and is active using UserDAO
        user = await user_dao.get_by_id(user_id)

        if not user or not user.is_active:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await connection_manager.connect(websocket, user_id)

        try:
            while True:
                # Keep connection alive, listen for messages (optional bi-directional)
                await websocket.receive_text()
        except WebSocketDisconnect:
            connection_manager.disconnect(websocket, user_id)

    except Exception:  # pylint: disable=broad-except
        # If any auth fails
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
