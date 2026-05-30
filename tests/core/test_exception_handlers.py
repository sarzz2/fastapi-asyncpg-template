# pylint: disable=redefined-outer-name,import-outside-toplevel
"""Tests for api/core/exception_handlers.py coverage gaps."""

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.exception_handlers import format_detail, register_exception_handlers


def test_format_detail_str() -> None:
    """Test format_detail with string input."""
    result = format_detail("Simple error message")
    assert result == "Simple error message"


def test_format_detail_non_standard() -> None:
    """Test format_detail with non-standard input returns str()."""
    result = format_detail({"weird": "dict"})
    assert "weird" in result


def test_format_detail_list_with_msg() -> None:
    """Test format_detail with validation error list."""
    errors = [{"loc": ["body", "field_name"], "msg": "value is required"}]
    result = format_detail(errors)
    assert "Field name: value is required" in result


@pytest.fixture
def app_with_handlers() -> FastAPI:
    """Create a FastAPI app with exception handlers registered."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/value-error")
    async def raise_value_error() -> None:
        raise ValueError("Test value error")

    @app.get("/key-error")
    async def raise_key_error() -> None:
        raise KeyError("test_key")

    @app.get("/permission-error")
    async def raise_permission_error() -> None:
        raise PermissionError("Access denied")

    @app.get("/not-implemented")
    async def raise_not_implemented() -> None:
        raise NotImplementedError("Feature not implemented")

    @app.get("/type-error")
    async def raise_type_error() -> None:
        raise TypeError("Type mismatch")

    return app


def test_value_error_handler(app_with_handlers: FastAPI) -> None:
    """Test ValueError handler (now falls back to 500)."""
    client = TestClient(app_with_handlers, raise_server_exceptions=False)
    response = client.get("/value-error")
    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"


def test_key_error_handler(app_with_handlers: FastAPI) -> None:
    """Test KeyError handler (now falls back to 500)."""
    client = TestClient(app_with_handlers, raise_server_exceptions=False)
    response = client.get("/key-error")
    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"


def test_permission_error_handler(app_with_handlers: FastAPI) -> None:
    """Test PermissionError handler."""
    client = TestClient(app_with_handlers)
    response = client.get("/permission-error")
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


def test_not_implemented_handler(app_with_handlers: FastAPI) -> None:
    """Test NotImplementedError handler."""
    client = TestClient(app_with_handlers)
    response = client.get("/not-implemented")
    assert response.status_code == 501
    assert "Feature not implemented" in response.json()["detail"]


def test_type_error_handler(app_with_handlers: FastAPI) -> None:
    """Test TypeError handler (now falls back to 500)."""
    client = TestClient(app_with_handlers, raise_server_exceptions=False)
    response = client.get("/type-error")
    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"


def test_unique_violation_fields_only(app_with_handlers: FastAPI) -> None:
    """Test unique violation handler with fields only, no values."""

    @app_with_handlers.get("/unique-fields-only")
    async def raise_unique_fields() -> None:
        exc = asyncpg.UniqueViolationError()
        exc.detail = "Key (username)="  # Malformed - no values
        raise exc

    client = TestClient(app_with_handlers)
    response = client.get("/unique-fields-only")
    # Should fall through to "fields" branch
    assert response.status_code == 400


def test_unique_violation_no_match(app_with_handlers: FastAPI) -> None:
    """Test unique violation handler when regex doesn't match."""

    @app_with_handlers.get("/unique-no-match")
    async def raise_unique_no_match() -> None:
        exc = asyncpg.UniqueViolationError()
        exc.detail = "Some other error message"  # No Key pattern
        raise exc

    client = TestClient(app_with_handlers)
    response = client.get("/unique-no-match")
    assert response.status_code == 400
    assert "same value already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generic_exception_handler_direct() -> None:
    """Test generic_exception_handler directly."""
    from unittest.mock import MagicMock

    app = FastAPI()
    register_exception_handlers(app)

    # Get the exception handler for Exception
    handler = app.exception_handlers.get(Exception)
    assert handler is not None

    # Create mock request and exception
    mock_request = MagicMock()
    exc = Exception("Test unhandled error")

    # Call handler directly
    import inspect

    response = handler(mock_request, exc)
    if inspect.isawaitable(response):
        response = await response

    assert response.status_code == 500
    assert response.body == b'{"detail":"Internal server error"}'
