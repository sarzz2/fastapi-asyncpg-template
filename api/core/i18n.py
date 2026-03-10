import json
import logging
import os
from contextvars import ContextVar
from typing import Any, Dict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from api.core.config import settings

# Context variable to store the current locale
_locale_ctx_var: ContextVar[str] = ContextVar("locale", default=settings.DEFAULT_LOCALE or "en")

# Simple in-memory cache for loaded translations
_translations_cache: Dict[str, Dict[str, Any]] = {}
log = logging.getLogger("fastapi")


class I18nMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle locale resolution and translation.
    """

    def __init__(self, app: ASGIApp, default_locale: str = "en", locale_dir: str = "api/locales"):
        """
        Initialize the middleware.
        Args:
            app: The ASGI application to wrap.
            default_locale: The default locale to use if none is specified.
            locale_dir: The directory containing the translation files.
        """
        super().__init__(app)
        self.default_locale = default_locale
        self.locale_dir = locale_dir

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Dispatch the request to the next middleware.
        Args:
            request: The request to dispatch.
            call_next: The next middleware to call.
        Returns:
            The response from the next middleware.
        """
        accept_language = request.headers.get("Accept-Language")
        locale_code = self.default_locale

        if accept_language:
            # Simple parsing; for robust parsing consider using babel.negotiate_locale
            try:
                # Take the first preferred language
                locale_code = accept_language.split(",")[0].split(";")[0].strip()
            except Exception as e:  # pylint: disable=broad-except
                log.warning("Could not parse Accept-Language header '%s': %s", accept_language, e)
                locale_code = self.default_locale

        _locale_ctx_var.set(locale_code)
        log.debug("Request locale set to: %s", locale_code)
        response = await call_next(request)
        return response


def get_locale() -> str:
    """Get the current locale."""
    return _locale_ctx_var.get()


def load_translations(locale: str) -> Dict[str, Any]:
    """Load translations from JSON file with caching."""
    if locale in _translations_cache:
        return _translations_cache[locale]

    locale_dir = os.path.join(os.getcwd(), "api/locales")
    file_path = os.path.join(locale_dir, f"{locale}.json")

    # Fallback for region codes (en-US -> en)
    if not os.path.exists(file_path) and "-" in locale:
        base_locale = locale.split("-")[0]
        file_path = os.path.join(locale_dir, f"{base_locale}.json")

    # Final fallback to default if not found (optional, or return empty)
    if not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)
            _translations_cache[locale] = data
            return data
    except Exception as e:  # pylint: disable=broad-except
        log.error("Failed to load translation file for locale '%s' at %s: %s", locale, file_path, e)
        return {}


def trans(message: str, **kwargs: Any) -> str:
    """
    Translate a message into the current locale.
    Supports dots for nested keys (e.g., 'auth.login.failed').
    """
    locale_code = get_locale()
    translations = load_translations(locale_code)

    # If not found in current locale, could try fallback to 'en' here
    if not translations and locale_code != "en":
        translations = load_translations("en")

    keys = message.split(".")
    value: Any = translations

    try:
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                value = None
                break

        if value is None:
            # Fallback to key if not found
            translated = message
        else:
            translated = str(value)

    except Exception as e:  # pylint: disable=broad-except
        log.warning("Failed to translate message key '%s' for locale '%s': %s", message, locale_code, e)
        translated = message

    if kwargs:
        try:
            return translated.format(**kwargs)
        except KeyError as e:
            log.warning("Missing format key %s in translation for '%s' (locale: %s)", e, message, locale_code)
            return translated

    return translated
