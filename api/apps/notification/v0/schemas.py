from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class NotificationType(str, Enum):
    """Notification type enum."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"


class NotificationSchema(BaseModel):
    """Notification schema."""

    type: NotificationType = Field(default=NotificationType.INFO)
    message: str
    subject: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Optional logic for overriding default email template structure
    template_path: str = Field(default="email/notification.html")

    # Optional logic for specialized actions (e.g. click_url)
    action_url: Optional[str] = None
