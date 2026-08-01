from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class CursorPage(BaseModel, Generic[T]):
    """
    Generic schema for cursor-based pagination.
    """

    items: List[T]
    next_cursor: Optional[str] = None
