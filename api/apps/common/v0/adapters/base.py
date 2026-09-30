from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from starlette.requests import Request


@dataclass(frozen=True)
class NormalizedWebhookEvent:
    """
    Standardized internal representation of an incoming webhook event.
    Decouples domain logic and storage from vendor-specific payload formats.
    """

    source: str
    event_id: str
    event_name: str
    resource_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)


class BaseWebhookAdapter(ABC):
    """
    Abstract Base Webhook Adapter.
    Translates vendor-specific HTTP requests and payloads into normalized events.
    """

    @abstractmethod
    def verify_signature(self, request: Request, raw_body: bytes, secret: str | None = None) -> bool:
        """
        Verify cryptographic signature from vendor request headers.

        Args:
            request: Starlette Request object.
            raw_body: Raw request body bytes.
            secret: Optional webhook signing secret.

        Returns:
            bool: True if signature is valid or verification is skipped.
        """

    @abstractmethod
    def normalize(self, request: Request, payload: dict[str, Any], raw_body: bytes) -> NormalizedWebhookEvent:
        """
        Normalize vendor payload and headers into a NormalizedWebhookEvent.

        Args:
            request: Starlette Request object.
            payload: Parsed JSON payload dictionary.
            raw_body: Raw bytes of request body.

        Returns:
            NormalizedWebhookEvent: Unified domain representation of the event.
        """

    def get_success_response(self) -> dict[str, Any]:
        """
        Vendor-specific HTTP success response dictionary.

        Returns:
            dict[str, Any]: Response payload returned to the webhook sender.
        """
        return {"status": "success"}
