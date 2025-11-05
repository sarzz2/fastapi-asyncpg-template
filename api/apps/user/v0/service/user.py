from fastapi import Depends, HTTPException, status

from api.apps.user.schemas.user import (
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)
from api.apps.user.v0.dao.user import UserDAO, get_user_dao
from api.core.auth import create_access_token, get_password_hash, verify_password


class UserService:
    """Service layer for user operations.

    This class expects a `UserDAO` to be injected. FastAPI will construct the
    DAO (and the DAO will obtain a database via its own Depends(get_db)).
    """

    def __init__(self, user_dao: UserDAO):
        self._user_dao = user_dao

    async def create_user(self, user_in: UserCreate) -> UserResponse:
        """
        Create a new user and return a response model.

        Args:
            user_in: User creation data

        Returns:
            UserResponse: Created user data
        """
        hashed_password = get_password_hash(user_in.password)
        user_db = await self._user_dao.create_user(user_in, hashed_password)
        return UserResponse.model_validate(user_db)

    async def authenticate_user(self, login_data: UserLogin) -> Token:
        """
        Authenticate user and return an access token.

        Args:
            login_data: User login credentials

        Returns:
            Token: Authentication token
        """
        user = await self._user_dao.get_by_username(login_data.username)
        if not user or not verify_password(login_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token_data = {"sub": user.username, "id": user.id}
        access_token = create_access_token(token_data)
        return Token(access_token=access_token)

    async def get_user_by_username(self, username: str) -> UserResponse:
        """
        Retrieve a user by username.

        Args:
            username: Username to search for

        Returns:
            UserResponse: User data
        """
        user_db = await self._user_dao.get_by_username(username)
        if not user_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        return UserResponse.model_validate(user_db)


async def get_user_service(user_dao: UserDAO = Depends(get_user_dao)) -> UserService:
    """
    Dependency to get UserService instance.
    Args:
        user_dao (UserDAO): The User Data Access Object.
    Returns:
        UserService: The User Service.
    """
    return UserService(user_dao=user_dao)
