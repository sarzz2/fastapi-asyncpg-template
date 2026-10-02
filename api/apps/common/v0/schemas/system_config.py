from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SystemConfigData(BaseModel):
    """System configuration schema matching system_configurations table."""

    id: int = 1
    enforce_mfa: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class SystemConfigUpdate(BaseModel):
    """Partial update payload for system configuration."""

    enforce_mfa: bool | None = None
