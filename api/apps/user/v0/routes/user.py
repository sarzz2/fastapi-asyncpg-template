from fastapi import APIRouter, Depends, Request, status

from api.apps.user.schemas.user import (
    LoginResponse,
    RefreshTokenRequest,
    Token,
    UserCreate,
    UserData,
    UserLogin,
    UserUpdate,
)
from api.apps.user.v0.service.user import UserService, get_user_service
from api.core.dependencies import get_current_user

router = APIRouter(tags=["users"])


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
        UserResponse: Created user data
    """
    return await svc.create_user(user_in)


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    login_data: UserLogin,
    svc: UserService = Depends(get_user_service),
) -> LoginResponse:
    """
    Authenticate user and return access token.

    Args:
        request: FastAPI request object
        login_data: User login credentials
        svc: User service dependency
    Returns:
        Token: Authentication token
    """
    return await svc.authenticate_user(login_data, request)


@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    request: Request,
    token_request: RefreshTokenRequest,
    svc: UserService = Depends(get_user_service),
) -> Token:
    """
    Refresh access token using a refresh token.

    Args:
        request: The FastAPI request object.
        token_request: The request body containing the refresh token.
        svc: The user service dependency.
    Returns:
        A new access token.
    """
    return await svc.refresh_token(token_request.refresh_token, request)


@router.get("/me", response_model=UserData)
async def me(
    user: UserData = Depends(get_current_user),
) -> UserData:
    """
    Get the currently authenticated user.

    Args:
        current_user: The currently authenticated user
    Returns:
        UserResponse: Current user data
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
        UserResponse: Updated user data
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
