import datetime
import uuid
from typing import Optional

from pydantic import UUID4, BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserBase(BaseModel):
    """Base model containing common user fields"""

    username: str = Field(..., min_length=3, max_length=50)


class UserAuthBase(UserBase):
    """Base model for authentication-related operations"""

    password: str = Field(..., min_length=8)

    @field_validator("password")
    @classmethod
    def password_strength(cls, password: str) -> str:
        # Add password validation logic if needed
        return password


class UserIn(UserAuthBase):
    """Model for user creation"""

    id: UUID4 = Field(default_factory=uuid.uuid4)
    email: EmailStr = Field(...)
    profile_picture_url: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"username": "johndoe", "email": "john.doe@example.com", "password": "securepassword123"}
        }
    )


# pylint: disable=W0107
class UserLogin(UserAuthBase):
    """Model for user login"""

    # Username already inherited from UserBase
    # Password already inherited from UserAuthBase
    pass


class UserModel(UserBase):
    """Model for user data response"""

    id: UUID4
    email: EmailStr
    profile_picture_url: Optional[str] = None
    is_verified: bool = False
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)


class UserUpdate(BaseModel):
    """Model for user updates"""

    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    profile_picture_url: Optional[str] = None
    is_verified: Optional[bool] = None


class PasswordChange(BaseModel):
    """Model for password changes"""

    current_password: str
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def passwords_match(cls, password: str, values) -> str:
        if "current_password" in values.data and password == values.data["current_password"]:
            raise ValueError("New password must be different from current password")
        return password


class TokenData(BaseModel):
    """Model for authentication tokens"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class Session(BaseModel):
    """Model for user sessions"""

    user_id: UUID4
    username: str
    jti: str  # JWT ID
    issued_at: datetime.datetime
    expires_at: datetime.datetime
    user_agent: str
