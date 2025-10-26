# from typing import Any, Callable, Optional
#
# from fastapi import Depends, HTTPException, Request
# from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis

# from starlette import status
#
# from app.core.auth import verify_token
from api.core.redis import RedisClient

# from app.schemas.user import UserModel
# from app.services.v0.user_service import get_additional_user_details, get_user
#
# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v0/users/login")
redis_client = RedisClient()


#
# credentials_exception = HTTPException(
#     status_code=status.HTTP_401_UNAUTHORIZED,
#     detail="Could not validate credentials",
#     headers={"WWW-Authenticate": "Bearer"},
# )
#
# email_exception = HTTPException(
#     status_code=status.HTTP_403_FORBIDDEN,
#     detail="email_not_found",
# )
#
#
# async def get_authenticated_user(token: str = Depends(oauth2_scheme)) -> UserModel:
#     """
#     Authenticate via JWT and load the user, but do NOT enforce email.
#     """
#     token_data = await verify_token(token)
#     if not token_data:
#         raise credentials_exception
#     user = await get_user(token_data.id)
#     if not user:
#         raise credentials_exception
#     return user
#
#
# async def get_current_user(token: str = Depends(oauth2_scheme)):
#     token_data = await verify_token(token)
#     user = await get_user(token_data.id)
#     if user.email is None:
#         raise email_exception
#     if user is None:
#         raise credentials_exception
#     return user
#
#
# async def get_current_additional_user_details(token: str = Depends(oauth2_scheme)):
#     """
#     Get the current user with additional details.
#     This is used for endpoints that require more than just the basic user info.
#     """
#     token_data = await verify_token(token)
#     user = await get_additional_user_details(token_data.id)
#     if user is None:
#         raise credentials_exception
#     if user is None:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="User details not found",
#         )
#     return user
#
#
# async def get_sudo_user(token: str = Depends(oauth2_scheme)):
#     try:
#         token_data = await verify_token(token, "sudo")
#         user = await get_user(token_data.id)
#         if user is None:
#             raise credentials_exception
#         if token_data.type != "sudo":
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Sudo access required",
#             )
#         return user
#     except JWTError:
#         raise credentials_exception
#
#
# def require_role(*allowed_roles: str) -> Callable[..., Any]:
#     """
#     Returns an async dependency function that:
#       1) Depends on get_current_user()
#       2) Raises 403 if current_user.role is not in allowed_roles
#       3) Otherwise returns current_user.
#     """
#
#     async def role_checker(
#         current_user: UserModel = Depends(get_current_user),
#     ) -> UserModel:
#         if current_user.role not in allowed_roles:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Forbidden: insufficient role",
#             )
#         return current_user
#
#     return role_checker
#
#
async def get_redis() -> Redis:
    return redis_client.client
