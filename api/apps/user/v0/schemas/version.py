from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AppVersionCheck(BaseModel):
    """
    Schema for checking app version.
    """

    platform: str
    app_version: str | None = None
    app_build: int | None = None


class ForceUpdateResponse(BaseModel):
    """
    Schema for force update response.
    """

    update_required: bool
    force: bool
    message: str
    latest_build: int
    min_build: int
    update_url: str | None = None


class AppVersionData(BaseModel):
    """
    Schema for full app version data.
    """

    platform: str
    min_build: int
    latest_build: int
    force_update: bool
    update_message: str | None = None
    update_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AppVersionUpdate(BaseModel):
    """
    Schema for app version update request.
    """

    min_build: int | None = None
    latest_build: int | None = None
    force_update: bool | None = None
    update_message: str | None = None
    update_url: str | None = None
