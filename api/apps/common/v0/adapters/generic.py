from typing import Any
from uuid import uuid4

from starlette.requests import Request

from api.apps.common.v0.adapters.base import BaseWebhookAdapter, NormalizedWebhookEvent


class GenericWebhookAdapter(BaseWebhookAdapter):
    """
    Default fallback adapter for generic or arbitrary inbound webhooks.
    """

    def verify_signature(self, request: Request, raw_body: bytes, secret: str | None = None) -> bool:
        """Allow generic requests unless specific validation is configured."""
        return True

    def normalize(self, request: Request, payload: dict[str, Any], raw_body: bytes) -> NormalizedWebhookEvent:
        """
        Normalize generic webhook payloads into NormalizedWebhookEvent.
        """
        event_id = str(payload.get("id") or payload.get("event_id") or f"gen_{uuid4().hex}")
        event_name = str(payload.get("event") or payload.get("type") or "generic.event")
        resource_id = str(payload.get("resource_id") or "") if payload.get("resource_id") else None

        return NormalizedWebhookEvent(
            source="generic",
            event_id=event_id,
            event_name=event_name,
            resource_id=resource_id,
            payload=payload,
            raw_payload=payload,
        )

    def get_success_response(self) -> dict[str, Any]:
        """Generic acknowledgment."""
        return {"status": "received", "source": "generic"}
