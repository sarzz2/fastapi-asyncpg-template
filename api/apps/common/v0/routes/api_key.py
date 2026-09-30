from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Security, status

from api.apps.common.v0.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyData,
    ApiKeyRotateResponse,
    ApiKeyUpdate,
)
from api.apps.common.v0.service.api_key import ApiKeyService, get_api_key_service
from api.apps.user.v0.schemas.user import UserData
from api.core.dependencies import get_current_user
from api.utils.pagination import Page, PaginationParams, apply_cursor_pagination

router = APIRouter()


@router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_in: ApiKeyCreate,
    service: ApiKeyService = Depends(get_api_key_service),
    current_user: UserData = Security(get_current_user, scopes=["api_keys:create"]),
) -> ApiKeyCreateResponse:
    """
    Create a new API key.
    Returns the raw secret key once in the response. Store it securely.
    """
    return await service.create_api_key(key_in, created_by=current_user.id)


@router.get("", response_model=Page[ApiKeyData])
async def list_api_keys(
    pagination: Annotated[PaginationParams, Query()],
    service: ApiKeyService = Depends(get_api_key_service),
    _current_user: UserData = Security(get_current_user, scopes=["api_keys:read"]),
) -> Page[ApiKeyData]:
    """
    List API keys with cursor-based pagination.
    """
    return await apply_cursor_pagination(
        fetch_func=service.list_api_keys,
        params=pagination,
        get_cursor_value=lambda x: str(x.id),
    )


@router.get("/{key_id}", response_model=ApiKeyData)
async def get_api_key(
    key_id: UUID,
    service: ApiKeyService = Depends(get_api_key_service),
    _current_user: UserData = Security(get_current_user, scopes=["api_keys:read"]),
) -> ApiKeyData:
    """
    Get API key metadata by ID.
    """
    return await service.get_api_key(key_id)


@router.patch("/{key_id}", response_model=ApiKeyData)
async def update_api_key(
    key_id: UUID,
    update_in: ApiKeyUpdate,
    service: ApiKeyService = Depends(get_api_key_service),
    _current_user: UserData = Security(get_current_user, scopes=["api_keys:update"]),
) -> ApiKeyData:
    """
    Update an API key's name, scopes, rate limit, expiration, or active status.
    """
    return await service.update_api_key(key_id, update_in)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: UUID,
    service: ApiKeyService = Depends(get_api_key_service),
    _current_user: UserData = Security(get_current_user, scopes=["api_keys:delete"]),
) -> None:
    """
    Delete an API key. Evicts the key from Redis cache immediately.
    """
    await service.delete_api_key(key_id)


@router.post("/{key_id}/rotate", response_model=ApiKeyRotateResponse)
async def rotate_api_key(
    key_id: UUID,
    service: ApiKeyService = Depends(get_api_key_service),
    _current_user: UserData = Security(get_current_user, scopes=["api_keys:update"]),
) -> ApiKeyRotateResponse:
    """
    Rotate an API key secret. Immediately invalidates old key and returns the new secret once.
    """
    return await service.rotate_api_key(key_id)
