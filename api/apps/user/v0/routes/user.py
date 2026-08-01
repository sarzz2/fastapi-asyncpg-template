from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Security, status

from api.apps.user.v0.schemas.user import UserCreate, UserData, UserRoleAssignment, UserSessionData, UserUpdate
from api.apps.user.v0.service.user import UserService, get_user_service
from api.core.dependencies import get_current_user
from api.schemas.pagination import CursorPage

router = APIRouter()


@router.post("/register", response_model=UserData, status_code=status.HTTP_201_CREATED)
async def register_user(
    user_in: UserCreate,
    svc: UserService = Depends(get_user_service),
) -> UserData:
    """
    Register a new user.

    Args:
        user_in: User registration data
        svc: User service dependency
    Returns:
        UserData: Created user data
    """
    return await svc.create_user(user_in)


@router.get("/me", response_model=UserData)
async def me(
    user: UserData = Depends(get_current_user),
) -> UserData:
    """
    Get the currently authenticated user.

    Args:
        user: The currently authenticated user
    Returns:
        UserData: Current user data
    """
    return user


@router.patch("/", response_model=UserData)
async def update_user(
    user_update: UserUpdate,
    current_user: UserData = Depends(get_current_user),
    svc: UserService = Depends(get_user_service),
) -> UserData:
    """
    Update the currently authenticated user's information.

    Args:
        user_update: User data to update
        current_user: The currently authenticated user
        svc: User service dependency
    Returns:
        UserData: Updated user data
    """
    return await svc.update_user(current_user.id, user_update)


@router.delete("/sessions/{jti}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    jti: str,
    current_user: UserData = Depends(get_current_user),
    svc: UserService = Depends(get_user_service),
) -> None:
    """
    Revoke a user session by its JTI.

    Args:
        jti: The JTI of the session to revoke
        current_user: The currently authenticated user
        svc: User service dependency
    Returns:
        None
    """
    await svc.revoke_user_session(current_user.id, jti)


@router.delete("/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_sessions(
    current_user: UserData = Depends(get_current_user),
    svc: UserService = Depends(get_user_service),
) -> None:
    """
    Revoke all sessions for the current user.

    Args:
        current_user: The currently authenticated user
        svc: User service dependency
    Returns:
        None
    """
    await svc.revoke_all_user_sessions(current_user.id)


@router.get("/sessions", response_model=CursorPage[UserSessionData])
async def get_sessions(
    limit: int = Query(10, ge=1, le=100),
    cursor: Optional[UUID] = Query(None),
    current_user: UserData = Depends(get_current_user),
    svc: UserService = Depends(get_user_service),
) -> CursorPage[UserSessionData]:
    """
    Get paginated user sessions.

    Args:
        limit: Number of items to return
        cursor: The cursor (last session ID)
        current_user: The currently authenticated user
        svc: User service dependency

    Returns:
        CursorPage[UserSessionData]: Paginated sessions
    """
    return await svc.get_user_sessions(current_user.id, limit, cursor)


@router.post("/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
async def assign_roles(
    user_id: UUID,
    role_assignment: UserRoleAssignment,
    svc: UserService = Depends(get_user_service),
    _current_user: UserData = Security(get_current_user, scopes=["users:update"]),
) -> None:
    """
    Assign roles to a user.
    Requires 'users:update' scope.
    """
    await svc.assign_roles_to_user(user_id, role_assignment.role_ids)
