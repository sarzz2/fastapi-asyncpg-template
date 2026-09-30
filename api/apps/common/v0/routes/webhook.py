import logging
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security, status

from api.apps.common.constants import WebhookDirection, WebhookEvents, WebhookStatus
from api.apps.common.v0.factories import WebhookAdapterFactory
from api.apps.common.v0.schemas.webhook import WebhookEndpointCreate, WebhookEndpointData, WebhookEndpointUpdate
from api.apps.common.v0.schemas.webhook_log import WebhookLogCreate
from api.apps.common.v0.service.webhook import WebhookService, get_webhook_service
from api.apps.common.v0.service.webhook_log import WebhookLogService, get_webhook_log_service
from api.apps.user.v0.schemas.user import UserData
from api.core.dependencies import get_current_user
from api.utils.pagination import Page, PaginationParams, apply_cursor_pagination

logger = logging.getLogger("fastapi")

router = APIRouter()


@router.post("", response_model=WebhookEndpointData, status_code=status.HTTP_201_CREATED)
async def create_webhook_endpoint(
    endpoint_in: WebhookEndpointCreate,
    service: WebhookService = Depends(get_webhook_service),
    current_user: UserData = Security(get_current_user, scopes=["webhooks:create"]),
) -> WebhookEndpointData:
    """
    Register a new outbound webhook endpoint.
    Subscribed event_types are validated against application WebhookEvents.
    """
    return await service.create_endpoint(endpoint_in, created_by=current_user.id)


@router.get("/events", response_model=list[str])
async def list_available_webhook_events(
    _current_user: UserData = Security(get_current_user, scopes=["webhooks:read"]),
) -> list[str]:
    """
    List all supported webhook event types that endpoints can subscribe to.
    """
    return [e.value for e in WebhookEvents]


@router.get("", response_model=Page[WebhookEndpointData])
async def list_webhook_endpoints(
    pagination: Annotated[PaginationParams, Query()],
    service: WebhookService = Depends(get_webhook_service),
    _current_user: UserData = Security(get_current_user, scopes=["webhooks:read"]),
) -> Page[WebhookEndpointData]:
    """
    List configured webhook endpoints with cursor pagination.
    """
    return await apply_cursor_pagination(
        fetch_func=service.list_endpoints,
        params=pagination,
        get_cursor_value=lambda x: str(x.id),
    )


@router.get("/{endpoint_id}", response_model=WebhookEndpointData)
async def get_webhook_endpoint(
    endpoint_id: UUID,
    service: WebhookService = Depends(get_webhook_service),
    _current_user: UserData = Security(get_current_user, scopes=["webhooks:read"]),
) -> WebhookEndpointData:
    """
    Retrieve webhook endpoint details.
    """
    return await service.get_endpoint(endpoint_id)


@router.patch("/{endpoint_id}", response_model=WebhookEndpointData)
async def update_webhook_endpoint(
    endpoint_id: UUID,
    update_in: WebhookEndpointUpdate,
    service: WebhookService = Depends(get_webhook_service),
    _current_user: UserData = Security(get_current_user, scopes=["webhooks:update"]),
) -> WebhookEndpointData:
    """
    Update webhook endpoint URL, subscribed event types, custom headers, secret, or active status.
    """
    return await service.update_endpoint(endpoint_id, update_in)


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook_endpoint(
    endpoint_id: UUID,
    service: WebhookService = Depends(get_webhook_service),
    _current_user: UserData = Security(get_current_user, scopes=["webhooks:delete"]),
) -> None:
    """
    Delete a webhook endpoint.
    """
    await service.delete_endpoint(endpoint_id)


def _process_inbound_adapter(
    source: str, request: Request, raw_body: bytes, payload: dict[str, Any]
) -> tuple[str, WebhookStatus, int, dict[str, Any], str | None]:
    """Verify inbound signature and normalize event payload via vendor adapter."""
    adapter = WebhookAdapterFactory.get_adapter(source)
    if not adapter.verify_signature(request, raw_body):
        logger.error("Invalid signature for %s webhook.", source)
        err = f"Invalid signature for {source} webhook."
        return f"{source}.event", WebhookStatus.FAILED, status.HTTP_401_UNAUTHORIZED, {"error": err}, err

    try:
        normalized_event = adapter.normalize(request, payload, raw_body)
        return (
            normalized_event.event_name,
            WebhookStatus.SUCCESS,
            status.HTTP_200_OK,
            adapter.get_success_response(),
            None,
        )
    except HTTPException as http_exc:
        err = str(http_exc.detail)
        return f"{source}.event", WebhookStatus.FAILED, http_exc.status_code, {"error": err}, err
    except (KeyError, ValueError, TypeError) as exc:
        err = str(exc)
        return f"{source}.event", WebhookStatus.FAILED, status.HTTP_400_BAD_REQUEST, {"error": err}, err


@router.post("/inbound/{source}", status_code=status.HTTP_200_OK)
async def handle_inbound_webhook(
    source: str,
    request: Request,
    log_service: WebhookLogService = Depends(get_webhook_log_service),
) -> dict[str, Any]:
    """
    Receiver for third-party inbound webhooks (e.g., Stripe, GitHub, Sendgrid).
    Dispatches to registered vendor adapter via WebhookAdapterFactory,
    normalizes the incoming payload, and logs to TimescaleDB.
    """
    start_time = time.perf_counter()
    raw_body = await request.body()
    try:
        payload: dict[str, Any] = await request.json()
    except (ValueError, UnicodeDecodeError):
        payload = {"raw": raw_body.decode("utf-8", errors="replace")}

    event_name, status_enum, status_code, response_data, error_message = _process_inbound_adapter(
        source, request, raw_body, payload
    )

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
    client_ip = request.client.host if request.client else None

    await log_service.log_event(
        WebhookLogCreate(
            direction=WebhookDirection.INBOUND,
            endpoint_id=None,
            source=source,
            event_name=str(event_name),
            url=str(request.url.path),
            status=status_enum,
            status_code=status_code,
            payload=payload,
            request_headers=dict(request.headers),
            response_headers={"content-type": "application/json"},
            response_body=str(response_data),
            execution_time_ms=elapsed_ms,
            ip_address=client_ip,
            error_message=error_message,
        )
    )

    if status_enum == WebhookStatus.FAILED:
        raise HTTPException(status_code=status_code, detail=error_message)

    return response_data
