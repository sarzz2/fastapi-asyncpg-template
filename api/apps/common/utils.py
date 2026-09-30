import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status

from api.constants import Environments
from api.core.config import settings


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a secure, high-entropy API key.

    Returns:
        tuple[str, str, str]: (raw_key, prefix, hashed_key)
    """
    rand_token = secrets.token_urlsafe(32)
    raw_key = f"ak_live_{rand_token}"
    prefix = raw_key[:16]
    hashed_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return raw_key, prefix, hashed_key


def hash_api_key(raw_key: str) -> str:
    """
    Hash a raw API key using SHA-256.

    Args:
        raw_key: Raw API key to hash

    Returns:
        str: SHA-256 hex digest
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_webhook_signature(secret: str, timestamp: str, payload_bytes: bytes) -> str:
    """
    Generate an HMAC-SHA256 signature for a webhook payload.

    Args:
        secret (str): The shared endpoint signing secret.
        timestamp (str): The Unix timestamp string.
        payload_bytes (bytes): The raw UTF-8 payload bytes.

    Returns:
        str: Hexadecimal HMAC-SHA256 digest.
    """
    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    return hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()


def verify_webhook_signature(
    secret: str,
    signature_header: str,
    payload_bytes: bytes,
    tolerance_seconds: int = 300,
) -> bool:
    """
    Verify an incoming webhook HMAC-SHA256 signature against timestamp and secret.

    Expected header format: 't={timestamp},v1={signature}'

    Args:
        secret (str): The shared endpoint signing secret.
        signature_header (str): Value of the X-Webhook-Signature header.
        payload_bytes (bytes): The raw UTF-8 payload bytes.
        tolerance_seconds (int): Maximum allowed drift between current time and signature timestamp.

    Returns:
        bool: True if signature matches and is within tolerance, False otherwise.
    """
    if not signature_header or not secret:
        return False

    elements = {}
    for part in signature_header.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            elements[k.strip()] = v.strip()

    timestamp_str = elements.get("t")
    received_sig = elements.get("v1")
    if not timestamp_str or not received_sig:
        return False

    try:
        timestamp_int = int(timestamp_str)
    except ValueError:
        return False

    now = int(time.time())
    if abs(now - timestamp_int) > tolerance_seconds:
        return False

    expected_sig = generate_webhook_signature(secret, timestamp_str, payload_bytes)
    return hmac.compare_digest(expected_sig, received_sig)


def parse_headers(raw: Any) -> dict[str, str]:
    """
    Parse raw header input (JSON string, dict, or 'Key: Value' lines) into a dictionary.

    Args:
        raw (Any): Raw header data.

    Returns:
        dict[str, str]: Clean dictionary of HTTP headers.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text == "{}":
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, ValueError):
            pass
        headers: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
            elif "=" in line:
                k, v = line.split("=", 1)
                headers[k.strip()] = v.strip()
        return headers
    return {}


def validate_webhook_url(url: str) -> None:
    """
    Validate target webhook URL and prevent SSRF attacks in staging and production.

    Args:
        url (str): The URL to validate.

    Raises:
        HTTPException: 400 Bad Request if the URL is invalid or points to a forbidden address.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook URL must use HTTP or HTTPS scheme.",
        )

    # In local/test environments, allow localhost / private IPs
    if settings.ENV in (Environments.DEV.value, Environments.TEST.value):
        return

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid hostname in webhook URL.",
        )

    try:
        ip_obj = ipaddress.ip_address(socket.gethostbyname(hostname))
    except (socket.gaierror, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not resolve webhook hostname.",
        ) from exc

    if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook URL points to a forbidden private or local network address.",
        )
