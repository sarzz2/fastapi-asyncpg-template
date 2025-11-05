from fastapi import APIRouter, Depends, status

from api.apps.user.schemas.user import Token, UserCreate, UserLogin, UserResponse
from api.apps.user.v0.service.user import UserService, get_user_service
from api.core.dependencies import get_current_user

router = APIRouter(tags=["users"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    user_in: UserCreate,
    svc: UserService = Depends(UserService),
) -> UserResponse:
    """
    Register a new user.

    Args:
        user_in: User registration data
        svc: User service dependency
    Returns:
        UserResponse: Created user data
    """
    return await svc.create_user(user_in)


@router.post("/login", response_model=Token)
async def login(
    login_data: UserLogin,
    svc: UserService = Depends(get_user_service),
) -> Token:
    """
    Authenticate user and return access token.

    Args:
        login_data: User login credentials
        svc: User service dependency
    Returns:
        Token: Authentication token
    """
    return await svc.authenticate_user(login_data)


@router.get("/me", response_model=UserResponse)
async def current_user(
    user: UserResponse = Depends(get_current_user),
) -> UserResponse:
    """
    Get the currently authenticated user.

    Args:
        current_user: The currently authenticated user
    Returns:
        UserResponse: Current user data
    """
    return user
