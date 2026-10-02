from enum import Enum
from typing import Any

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
    subject: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Optional logic for overriding default email template structure
    template_path: str = Field(default="email/notification.html")

    # Optional logic for specialized actions (e.g. click_url)
    action_url: str | None = None


class DeviceRegisterRequest(BaseModel):
    """Schema for registering a push device token."""

    fcm_token: str = Field(..., min_length=10, max_length=500)
    platform: str = Field(..., pattern="^(ios|android|web)$")
    device_name: str | None = Field(default=None, max_length=100)


class DeviceResponse(BaseModel):
    """Schema for device details response."""

    id: Any
    user_id: Any
    fcm_token: str
    platform: str
    device_name: str | None
    is_active: bool
    created_at: Any
    last_used_at: Any
