import json
import logging
import time

import httpx

from api.apps.common.constants import WebhookDirection, WebhookStatus
from api.apps.common.utils import generate_webhook_signature
from api.apps.common.v0.schemas.webhook import WebhookEndpointData
from api.apps.common.v0.schemas.webhook_log import WebhookLogCreate
from api.core.celery_app import AsyncBaseTask, celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="common.send_webhook_event",
    base=AsyncBaseTask,
    bind=True,
)
def send_webhook_event(
    self: AsyncBaseTask,
    event_name: str,
    payload: dict,
    event_id: str,
) -> None:
    """
    Celery task to deliver outbound webhook events for a given event name.
    Queries all active endpoints subscribed to event_name, signs the payload
    with HMAC-SHA256, and logs each delivery attempt to TimescaleDB webhook_logs.

    Args:
        self: AsyncBaseTask
        event_name: Name of the event (e.g. user.created)
        payload: Payload dictionary to send
        event_id: Unique event ID
    """
    logger.info(
        "Executing webhook event delivery task: event=%s, event_id=%s, attempt=%s",
        event_name,
        event_id,
        self.request.retries + 1,
    )

    async def _deliver_to_endpoint(
        client: httpx.AsyncClient,
        endpoint: WebhookEndpointData,
        timestamp: str,
        body_bytes: bytes,
    ) -> None:
        signature = generate_webhook_signature(endpoint.secret, timestamp, body_bytes)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "FastAPI-Template-Webhook/1.0",
            "X-Webhook-ID": event_id,
            "X-Webhook-Event": event_name,
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": f"t={timestamp},v1={signature}",
        }
        if endpoint.headers:
            headers.update(endpoint.headers)

        start_time = time.perf_counter()
        response_status_code: int | None = None
        response_headers: dict | None = None
        response_body: str | None = None
        error_message: str | None = None
        delivery_status = WebhookStatus.SUCCESS

        try:
            response = await client.post(endpoint.url, content=body_bytes, headers=headers)
            response_status_code = response.status_code
            response_headers = dict(response.headers)
            response_body = response.text

            if not response.is_success:
                delivery_status = WebhookStatus.FAILED
                error_message = f"Received non-2xx status code: {response.status_code}"

        except (httpx.HTTPError, OSError) as exc:
            error_message = str(exc)
            delivery_status = WebhookStatus.FAILED

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        await self.container.webhook_log_dao.create_log(
            WebhookLogCreate(
                direction=WebhookDirection.OUTBOUND,
                endpoint_id=endpoint.id,
                source="system",
                event_name=event_name,
                url=endpoint.url,
                status=delivery_status,
                status_code=response_status_code,
                payload=payload,
                request_headers=headers,
                response_headers=response_headers,
                response_body=response_body,
                execution_time_ms=elapsed_ms,
                error_message=error_message,
            )
        )

    async def _deliver() -> None:
        endpoints = await self.container.webhook_dao.list_active_endpoints_for_event(event_name)
        if not endpoints:
            logger.info("No active webhook endpoints subscribed to event: %s", event_name)
            return

        timestamp = str(int(time.time()))
        body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        async with httpx.AsyncClient(timeout=10.0) as client:
            for endpoint in endpoints:
                await _deliver_to_endpoint(client, endpoint, timestamp, body_bytes)

    coro = _deliver()
    try:
        self.loop.run_until_complete(coro)
    finally:
        coro.close()
