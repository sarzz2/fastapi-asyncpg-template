"""
Unit tests for Webhook schemas, services, and adapter pipelines.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from api.apps.common.constants import WebhookDirection, WebhookEvents, WebhookStatus
from api.apps.common.v0.adapters.base import NormalizedWebhookEvent
from api.apps.common.v0.adapters.generic import GenericWebhookAdapter
from api.apps.common.v0.dao.webhook_log import WebhookLogDAO
from api.apps.common.v0.factories.webhook import WebhookAdapterFactory
from api.apps.common.v0.schemas.webhook import WebhookEndpointCreate
from api.apps.common.v0.schemas.webhook_log import WebhookLogCreate
from api.apps.common.v0.service.webhook import WebhookService
from api.apps.common.v0.service.webhook_log import WebhookLogService


def test_webhook_schema_valid_events() -> None:
    """Verify WebhookEndpointCreate schema with valid registered event types."""
    data = WebhookEndpointCreate(
        url="https://api.example.com/webhook",
        event_types=[WebhookEvents.USER_CREATED.value, WebhookEvents.USER_UPDATED.value],
    )
    assert len(data.event_types) == 2


def test_webhook_schema_invalid_events() -> None:
    """Verify WebhookEndpointCreate validation failure on unregistered event types."""
    with pytest.raises(ValidationError):
        WebhookEndpointCreate(
            url="https://api.example.com/webhook",
            event_types=["invalid.event.name"],
        )


@pytest.mark.asyncio
async def test_webhook_service_dispatch() -> None:
    """Verify WebhookService.dispatch_event_to_endpoints enqueues Celery delivery task."""
    service = WebhookService(dao=AsyncMock())

    with patch("api.core.celery_app.celery_app.send_task") as mock_send_task:
        success = await service.dispatch_event_to_endpoints(
            event_name=WebhookEvents.USER_CREATED.value,
            payload={"user_id": "12345"},
            event_id="evt_12345",
        )
        assert success is True
        mock_send_task.assert_called_once_with(
            "common.send_webhook_event",
            args=[WebhookEvents.USER_CREATED.value, {"user_id": "12345"}, "evt_12345"],
        )


@pytest.mark.asyncio
async def test_webhook_log_service() -> None:
    """Verify WebhookLogService records delivery logs to DAO."""
    mock_log_dao = AsyncMock(spec=WebhookLogDAO)
    service = WebhookLogService(dao=mock_log_dao)
    log_in = WebhookLogCreate(
        direction=WebhookDirection.OUTBOUND,
        endpoint_id=uuid4(),
        source="system",
        event_name="user.created",
        url="https://example.com/webhook",
        status=WebhookStatus.SUCCESS,
        status_code=200,
        payload={"msg": "hello"},
    )
    await service.log_event(log_in)
    mock_log_dao.create_log.assert_awaited_once_with(log_in)


@pytest.mark.asyncio
async def test_webhook_adapter_factory_and_adapters() -> None:
    """Verify WebhookAdapterFactory resolves vendor adapters and normalizes payloads."""
    generic_adapter = WebhookAdapterFactory.get_adapter("generic")
    other_adapter = WebhookAdapterFactory.get_adapter("custom_service")

    assert isinstance(generic_adapter, GenericWebhookAdapter)
    assert isinstance(other_adapter, GenericWebhookAdapter)

    mock_request = MagicMock()
    mock_request.headers = {}
    normalized = other_adapter.normalize(mock_request, {"event": "ping", "id": "123"}, b'{"event": "ping"}')
    assert isinstance(normalized, NormalizedWebhookEvent)
    assert normalized.source == "generic"
    assert normalized.event_name == "ping"
    assert normalized.event_id == "123"
    assert other_adapter.get_success_response() == {"status": "received", "source": "generic"}
