from uuid import UUID

from fastapi import Depends

from api.apps.notification.v0.schemas import DeviceResponse
from api.core.database import DataBase, get_db


class DeviceDAO:
    """Data Access Object for user push notification devices."""

    def __init__(self, db: DataBase):
        self.db = db

    async def register_device(
        self,
        user_id: UUID,
        fcm_token: str,
        platform: str,
        device_name: str | None = None,
    ) -> DeviceResponse:
        """
        Register or reactivate a push device token for a user.
        Args:
            user_id (UUID): User ID.
            fcm_token (str): FCM token to register.
            platform (str): Platform of the device.
            device_name (str | None): Name of the device.
        Returns:
            DeviceResponse: Registered device.
        """
        query = """
            INSERT INTO user_devices (
                user_id, fcm_token, platform, device_name, is_active, last_used_at, updated_at
            )
            VALUES ($1, $2, $3, $4, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (fcm_token) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                platform = EXCLUDED.platform,
                device_name = COALESCE(EXCLUDED.device_name, user_devices.device_name),
                is_active = TRUE,
                last_used_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            RETURNING *;
        """
        return await self.db.write(
            query,
            user_id,
            fcm_token,
            platform,
            device_name,
            model=DeviceResponse,
        )

    async def unregister_device(self, user_id: UUID, fcm_token: str) -> None:
        """
        Deactivate a device token for a user upon logout or unregistration.
        Args:
            user_id (UUID): User ID.
            fcm_token (str): FCM token to deactivate.
        Returns:
            None
        """
        query = """
            UPDATE user_devices
            SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1 AND fcm_token = $2;
        """
        await self.db.execute(query, user_id, fcm_token)

    async def get_active_devices_by_user(self, user_id: UUID) -> list[DeviceResponse]:
        """
        Retrieve all active devices registered for a specific user.
        Args:
            user_id (UUID): User ID.
        Returns:
            list[DeviceResponse]: List of active devices.
        """
        query = """
            SELECT * FROM user_devices
            WHERE user_id = $1 AND is_active = TRUE
            ORDER BY last_used_at DESC;
        """
        return await self.db.fetch(query, user_id, model=DeviceResponse, fetch_row=False)

    async def deactivate_tokens(self, tokens: list[str]) -> None:
        """
        Bulk deactivate invalid or unregistered tokens reported by FCM.
        Args:
            tokens (list[str]): List of FCM tokens to deactivate.
        Returns:
            None
        """
        if not tokens:
            return
        query = """
            UPDATE user_devices
            SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE fcm_token = ANY($1);
        """
        await self.db.execute(query, tokens)

    async def get_all_active_tokens(self) -> list[str]:
        """
        Retrieve all active FCM tokens across all users (for broadcasts).
        Returns:
            list[str]: List of active FCM tokens.
        """
        query = "SELECT fcm_token FROM user_devices WHERE is_active = TRUE;"
        records = await self.db.fetch(query, fetch_row=False)
        return [r["fcm_token"] for r in records]


def get_device_dao(db: DataBase = Depends(get_db)) -> DeviceDAO:
    """Dependency provider for DeviceDAO."""
    return DeviceDAO(db)
