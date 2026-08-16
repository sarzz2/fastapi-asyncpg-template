from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class CursorPage(BaseModel, Generic[T]):
    """
    Generic schema for cursor-based pagination.
    """

    items: list[T]
    next_cursor: str | None = None
