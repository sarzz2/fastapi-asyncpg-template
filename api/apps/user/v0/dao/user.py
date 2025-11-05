from typing import Optional

from fastapi import Depends

from api.apps.user.schemas.user import UserCreate, UserInDB
from api.core.database import DataBase, get_db


class UserDAO:
    """Data Access Object for user-related database operations."""

    def __init__(self, db: DataBase):
        self.db = db

    async def get_by_username(self, username: str) -> Optional[UserInDB]:
        """
        Retrieve a user by username.

        Args:
                db: Database instance for executing queries
                username: Username to search for

        Returns:
                Optional[UserInDB]: User if found, None otherwise
        """
        query = """
              SELECT * FROM users WHERE username = $1
        """
        # Use database layer's built-in model conversion
        return await self.db.fetch(query, username, model=UserInDB, fetch_row=True)

    async def create_user(
        self,
        user_data: UserCreate,
        hashed_password: str,
    ) -> UserInDB:
        """
        Create a new user in the database.

        Args:
                db: Database instance for executing queries
                user_data: User creation data
                hashed_password: Pre-hashed password

        Returns:
                UserInDB: Created user data
        """
        query = """
			INSERT INTO users (username, email, hashed_password, full_name, is_active)
			VALUES ($1, $2, $3, $4, $5)
			RETURNING *
		"""
        params = (
            user_data.username,
            user_data.email,
            hashed_password,
            user_data.full_name,
            user_data.is_active,
        )
        # Use database layer's built-in model conversion
        return await self.db.write(query, *params, model=UserInDB)


async def get_user_dao(db: DataBase = Depends(get_db)) -> UserDAO:
    """
    Dependency to get UserDAO instance.
    Args:
        db (DataBase): The database dependency.
    Returns:
        UserDAO: The User Data Access Object.
    """
    return UserDAO(db=db)
