from fastapi import APIRouter, Depends, status

from api.apps.user.schemas.user import Token, UserCreate, UserLogin, UserResponse
from api.apps.user.v0.service.user import UserService

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
        db: Database dependency

    Returns:
        UserResponse: Created user data
    """
    return await svc.create_user(user_in)


@router.post("/login", response_model=Token)
async def login(
    login_data: UserLogin,
    svc: UserService = Depends(UserService),
) -> Token:
    """
    Authenticate user and return access token.

    Args:
        login_data: User login credentials
        db: Database dependency

    Returns:
        Token: Authentication token
    """
    return await svc.authenticate_user(login_data)
