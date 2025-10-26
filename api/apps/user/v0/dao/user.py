from typing import Optional

from asyncpg import UniqueViolationError
from fastapi import Depends

from api.apps.user.schemas.user import UserCreate, UserInDB
from api.core.database import DataBase, get_db


class UserDAO:
    def __init__(self, db: DataBase = Depends(get_db)):
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
        # Get raw database result
        return await self.db.fetch(query, True, username, convert=True)
        

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
        try:
            # First get the raw database result
            return await self.db.write(query, *params)            
        except UniqueViolationError as e:
            raise e
        except Exception as e:
            raise e
