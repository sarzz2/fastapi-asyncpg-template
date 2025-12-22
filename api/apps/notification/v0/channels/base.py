from abc import ABC, abstractmethod
from uuid import UUID

from api.apps.notification.schemas import NotificationSchema


class BaseNotificationChannel(ABC):
    """
    Abstract base class for notification channels (e.g., WebSocket, Email, Push).
    """

    @abstractmethod
    async def send(self, user_id: UUID, notification: NotificationSchema) -> None:
        """
        Send a notification to a specific user.
        """

    @abstractmethod
    async def broadcast(self, notification: NotificationSchema) -> None:
        """
        Broadcast a notification to all users.
        """
