import binascii
from base64 import b64decode, b64encode
from typing import Any, Awaitable, Callable, Generic, Optional, Sequence, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


def encode_cursor(value: str) -> str:
    """
    Encodes a value into a base64 cursor string.
    Args:
        value (str): The value to encode.
    Returns:
        str: The encoded cursor string.
    """
    return b64encode(value.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor: str) -> str:
    """
    Decodes a base64 cursor string into its original value.
    Args:
        cursor (str): The cursor to decode.
    Returns:
        str: The decoded cursor string.
    """
    return b64decode(cursor.encode("utf-8")).decode("utf-8")


class PaginationParams(BaseModel):
    """
    Dependency class for pagination parameters.
    """

    first: int = Field(20, ge=1, le=100, description="Items per page")
    after: str | None = Field(None, description="Cursor for the next page")


class Page(BaseModel, Generic[T]):
    """
    Generic response model for paginated results.
    """

    items: Sequence[T]
    total_count: int | None = Field(None, description="Total number of items")
    page_info: dict[str, str | bool | None] = Field(..., description="Pagination metadata")

    @classmethod
    def create(
        cls,
        items: Sequence[T],
        total_count: int | None = None,
        end_cursor: str | None = None,
    ) -> "Page[T]":
        """
        Creates a new Page instance.
        Args:
            items (Sequence[T]): The items to include in the page.
            total_count (int | None): The total number of items.
            end_cursor (str | None): The cursor for the end of the page.
        Returns:
            Page[T]: The created Page instance.
        """
        return cls(
            items=items,
            total_count=total_count,
            page_info={
                "end_cursor": end_cursor,
            },
        )


async def apply_cursor_pagination(
    fetch_func: Callable[..., Awaitable[Sequence[T]]],
    params: PaginationParams,
    get_cursor_value: Callable[[T], str],
    count_func: Optional[Callable[[], Awaitable[int]]] = None,
    **kwargs: Any,
) -> Page[T]:
    """
    Helper function to apply cursor-based pagination.

    Args:
        fetch_func: Async function to fetch items. Must accept 'limit' and 'cursor' args.
        params: PaginationParams dependency.
        get_cursor_value: Function to extract the cursor value from an item.
        count_func: Optional async function to get the total count.
        **kwargs: Additional arguments to pass to fetch_func.

    Returns:
        Page[T]: The paginated response.
    """
    cursor_value: str | None = None
    if params.after:
        try:
            cursor_value = decode_cursor(params.after)
        except (ValueError, binascii.Error):
            pass  # Invalid cursor, start from beginning

    # Fetch one extra item to check if there is a next page
    limit = params.first + 1

    items = await fetch_func(limit=limit, cursor=cursor_value, **kwargs)

    if len(items) > params.first:
        items = items[: params.first]

    end_cursor = None
    if items:
        last_item = items[-1]
        end_cursor = encode_cursor(get_cursor_value(last_item))

    total_count = None
    if count_func:
        total_count = await count_func()

    return Page.create(items=items, total_count=total_count, end_cursor=end_cursor)
