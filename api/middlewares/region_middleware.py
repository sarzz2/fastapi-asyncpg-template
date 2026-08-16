import logging
import re
from typing import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send

from api.core.context import CLIENT_REGION

log = logging.getLogger("fastapi")

# default mapping (country code or short name -> your canonical region key)
DEFAULT_REGION_MAP = {
    "in": "ap-south",
    "india": "ap-south",
    "us": "us-east",
    "gb": "eu-west",
    "uk": "eu-west",
    "eu": "eu-west",
}

_WHITELIST_RE = re.compile(r"^[a-z0-9\-_]+$")


class RegionASGIMiddleware:
    """
    ASGI middleware to extract a region header injected by your edge,
    normalize + map it to canonical region keys, and set CLIENT_REGION contextvar.
    """

    def __init__(
        self,
        app: ASGIApp,
        header_names: Iterable[str] = ("x-geo-region", "x-cloud-region", "x-country"),
        mapping: dict[str, str | None] = None,
    ):
        """
        RegionASGIMiddleware constructor.

        Args:
            app (ASGIApp): The ASGI application to wrap.
            header_names (Iterable[str], optional): Header names to check for region info.
                Defaults to ("x-geo-region", "x-cloud-region", "x-country").
            mapping (Dict[str, str | None], optional): Mapping of raw header values to
                canonical region keys. Defaults to DEFAULT_REGION_MAP.
        """
        self.app = app
        self.header_names = tuple(n.lower() for n in header_names)
        self.mapping = {k.lower(): v for k, v in (mapping or DEFAULT_REGION_MAP).items()}

    def _headers_dict(self, scope: Scope) -> dict[str, str]:
        """
        Parse headers from ASGI scope into a dict.
        Args:
            scope (Scope): The ASGI scope containing headers.
        Returns:
            Dict[str, str]: Dictionary of header names and values.
        """
        # convert raw headers (bytes) into a simple dict[str,str]
        return {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}

    def _normalize_map(self, raw: str) -> str | None:
        """
        Normalize and map a raw header value to a canonical region key.
        Args:
            raw (str): The raw header value.
        Returns:
            str | None: The mapped canonical region key, or None if invalid/not mapped.
        """
        if not raw:
            return None
        v = raw.strip().lower()
        if not _WHITELIST_RE.match(v):
            log.debug("Region header value failed whitelist: %r", raw)
            return None
        return self.mapping.get(v, v)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        ASGI application entry point.
        Args:
            scope (Scope): The ASGI scope.
            receive (Receive): The ASGI receive callable.
            send (Send): The ASGI send callable.
        """
        headers = self._headers_dict(scope)
        chosen_raw = None
        for h in self.header_names:
            val = headers.get(h)
            if val and val.strip():
                chosen_raw = val
                break

        region = None
        if chosen_raw:
            region = self._normalize_map(chosen_raw)
            if region:
                log.debug("Region header accepted: raw=%s -> region=%s", chosen_raw, region)
            else:
                log.debug("Region header present but not mapped/valid: %s", chosen_raw)
        else:
            log.debug("No region header found in headers %s", self.header_names)

        token = CLIENT_REGION.set(region)
        scope.setdefault("state", {})["client_region"] = region
        try:
            await self.app(scope, receive, send)
        finally:
            CLIENT_REGION.reset(token)
