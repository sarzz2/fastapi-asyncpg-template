from datetime import datetime
from typing import Any, Dict
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from api.utils.date import get_utc_now


class ApplicationEvent(BaseModel):
    """
    Base schema for all application events published to the EventBus.
    Provides strict typing without forcing boilerplate subclasses for every event hook.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    event_id: UUID = Field(default_factory=uuid4)
    event_name: str
    timestamp: datetime = Field(default_factory=get_utc_now)
    payload: Dict[str, Any] = Field(default_factory=dict)
