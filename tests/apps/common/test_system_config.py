# pylint: disable=redefined-outer-name
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from api.apps.common.v0.dao.system_config import SystemConfigDAO
from api.apps.common.v0.routes.system_config import get_system_config, update_system_config
from api.apps.common.v0.schemas.system_config import SystemConfigData, SystemConfigUpdate
from api.apps.common.v0.service.system_config import SystemConfigService
from api.apps.user.v0.schemas.user import UserData
from api.core.database import DataBase


@pytest.fixture
def mock_db() -> AsyncMock:
    """Mock database instance."""
    return AsyncMock(spec=DataBase)


@pytest.fixture
def sample_config_data() -> SystemConfigData:
    """Sample SystemConfigData instance."""
    return SystemConfigData(
        id=1,
        enforce_mfa=False,
        updated_at=datetime.now(timezone.utc),
        updated_by=None,
    )


@pytest.fixture
def sample_user() -> UserData:
    """Sample UserData instance."""
    return UserData(
        id=uuid4(),
        email="admin@example.com",
        username="admin",
        is_active=True,
        created_at=datetime.now(timezone.utc),
        roles=[],
    )


@pytest.mark.asyncio
async def test_dao_get_config(mock_db: AsyncMock, sample_config_data: SystemConfigData) -> None:
    """Test SystemConfigDAO.get_config fetches singleton configuration."""
    with patch("api.core.cache._get_from_cache", new=AsyncMock(return_value=None)):
        mock_db.fetch = AsyncMock(return_value=sample_config_data)
        dao = SystemConfigDAO(db=mock_db)

        result = await dao.get_config()
        assert result == sample_config_data
        mock_db.fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_dao_update_config(mock_db: AsyncMock, sample_config_data: SystemConfigData) -> None:
    """Test SystemConfigDAO.update_config updates singleton configuration."""
    with patch("api.core.cache.redis_client.client.delete", new=AsyncMock()):
        mock_db.write = AsyncMock(return_value=sample_config_data)
        dao = SystemConfigDAO(db=mock_db)

        update_payload = SystemConfigUpdate(enforce_mfa=True)
        result = await dao.update_config(update_payload, user_id=uuid4())
        assert result == sample_config_data
        mock_db.write.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_get_and_patch_config(sample_config_data: SystemConfigData, sample_user: UserData) -> None:
    """Test authenticated endpoints get_system_config and update_system_config."""
    mock_svc = AsyncMock(spec=SystemConfigService)
    mock_svc.get_config.return_value = sample_config_data
    mock_svc.update_config.return_value = sample_config_data

    # Test GET
    get_res = await get_system_config(svc=mock_svc, _current_user=sample_user)
    assert get_res == sample_config_data

    # Test PATCH
    update_data = SystemConfigUpdate(enforce_mfa=True)
    patch_res = await update_system_config(update_data=update_data, svc=mock_svc, current_user=sample_user)
    assert patch_res == sample_config_data
    mock_svc.update_config.assert_awaited_once_with(update_data, sample_user.id)
