# pylint: disable=redefined-outer-name
"""Tests for api/core/pagination.py coverage gaps."""

import pytest

from api.core.pagination import PaginationParams, apply_cursor_pagination, decode_cursor, encode_cursor


def test_decode_cursor_valid() -> None:
    """Test decoding a valid cursor."""
    encoded = encode_cursor("test_value")
    decoded = decode_cursor(encoded)
    assert decoded == "test_value"


def test_decode_cursor_invalid() -> None:
    """Test decoding an invalid cursor raises error."""
    with pytest.raises(Exception):  # binascii.Error or ValueError
        decode_cursor("not_valid_base64!!!")


@pytest.mark.asyncio
async def test_apply_cursor_pagination_invalid_cursor() -> None:
    """Test pagination with invalid cursor falls back to beginning."""

    async def fetch_func(limit: int, cursor: str | None) -> list:  # pylint: disable=unused-argument
        # If cursor is None, we started from beginning
        assert cursor is None
        return ["item1", "item2"]

    params = PaginationParams(first=10, after="invalid_base64!!!")

    result = await apply_cursor_pagination(
        fetch_func=fetch_func,
        params=params,
        get_cursor_value=lambda x: x,
    )

    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_apply_cursor_pagination_with_count_func() -> None:
    """Test pagination with count function."""

    async def fetch_func(limit: int, cursor: str | None) -> list:  # pylint: disable=unused-argument
        return ["item1", "item2"]

    async def count_func() -> int:
        return 100

    params = PaginationParams(first=10, after=None)

    result = await apply_cursor_pagination(
        fetch_func=fetch_func,
        params=params,
        get_cursor_value=lambda x: x,
        count_func=count_func,
    )

    assert result.total_count == 100
