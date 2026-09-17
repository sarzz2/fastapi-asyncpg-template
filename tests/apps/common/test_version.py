# pylint: disable=W0621
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Response, status

from api.apps.common.v0.dao.version import VersionDAO
from api.apps.common.v0.routes.version import check_version, get_all_version_configs, update_version_config
from api.apps.common.v0.schemas.version import AppVersionData, AppVersionUpdate
from api.apps.common.v0.service.version import VersionService
from api.core.database import DataBase


@pytest.fixture
def mock_db() -> AsyncMock:
    """Mock database instance."""
    return AsyncMock(spec=DataBase)


@pytest.fixture
def sample_version_data() -> AppVersionData:
    """Sample AppVersionData instance."""
    return AppVersionData(
        id=uuid4(),
        platform="ios",
        min_build=10,
        latest_build=20,
        force_update=False,
        update_message="Update available",
        update_url="https://example.com/update",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_version_dao_get_version_info(mock_db: AsyncMock, sample_version_data: AppVersionData) -> None:
    """Test VersionDAO fetching version info for a platform."""

    with patch("api.core.cache._get_from_cache", new=AsyncMock(return_value=None)):
        mock_db.fetch = AsyncMock(return_value=sample_version_data)
        dao = VersionDAO(db=mock_db)

        result = await dao.get_version_info("IOS")
        assert result == sample_version_data
        mock_db.fetch.assert_awaited_once_with(
            "SELECT * FROM app_versions WHERE platform = $1",
            "ios",
            model=AppVersionData,
            fetch_row=True,
        )


@pytest.mark.asyncio
async def test_version_dao_get_all_versions(mock_db: AsyncMock, sample_version_data: AppVersionData) -> None:
    """Test VersionDAO fetching all versions."""

    with patch("api.core.cache._get_from_cache", new=AsyncMock(return_value=None)):
        mock_db.fetch = AsyncMock(return_value=[sample_version_data])
        dao = VersionDAO(db=mock_db)

        result = await dao.get_all_versions()
        assert len(result) == 1
        assert result[0] == sample_version_data
        mock_db.fetch.assert_awaited_once_with(
            "SELECT * FROM app_versions ORDER BY platform",
            model=AppVersionData,
            fetch_row=False,
        )


@pytest.mark.asyncio
async def test_version_dao_update_version_info(mock_db: AsyncMock, sample_version_data: AppVersionData) -> None:
    """Test VersionDAO updating version info."""
    mock_db.write = AsyncMock(return_value=sample_version_data)
    dao = VersionDAO(db=mock_db)

    update_payload = AppVersionUpdate(latest_build=25, force_update=True)
    result = await dao.update_version_info("android", update_payload)
    assert result == sample_version_data
    assert mock_db.write.call_count == 1


@pytest.mark.asyncio
async def test_version_service_check_force_update(sample_version_data: AppVersionData) -> None:
    """Test VersionService force update logic."""
    mock_dao = AsyncMock(spec=VersionDAO)
    mock_dao.get_version_info = AsyncMock(return_value=sample_version_data)

    service = VersionService(version_dao=mock_dao)

    # Below min build -> force update required
    res_forced = await service.check_force_update("ios", 5)
    assert res_forced is not None
    assert res_forced.force is True
    assert res_forced.update_required is True

    # Below latest build -> optional update
    res_optional = await service.check_force_update("ios", 15)
    assert res_optional is not None
    assert res_optional.force is False
    assert res_optional.update_required is True

    # Up to date -> None
    res_uptodate = await service.check_force_update("ios", 20)
    assert res_uptodate is None


@pytest.mark.asyncio
async def test_version_routes_check(sample_version_data: AppVersionData) -> None:
    """Test check_version route status code handling."""
    mock_dao = AsyncMock(spec=VersionDAO)
    mock_dao.get_version_info = AsyncMock(return_value=sample_version_data)
    service = VersionService(version_dao=mock_dao)

    response = Response()
    # Below min_build (10) -> force update status 426
    res = await check_version(platform="ios", build=5, response=response, svc=service)
    assert res is not None
    assert res.force is True
    assert response.status_code == status.HTTP_426_UPGRADE_REQUIRED


@pytest.mark.asyncio
async def test_version_routes_crud(sample_version_data: AppVersionData) -> None:
    """Test configs listing and update routes."""
    mock_dao = AsyncMock(spec=VersionDAO)
    mock_dao.get_all_versions = AsyncMock(return_value=[sample_version_data])
    mock_dao.update_version_info = AsyncMock(return_value=sample_version_data)
    service = VersionService(version_dao=mock_dao)

    configs = await get_all_version_configs(svc=service, _current_user=MagicMock())
    assert len(configs) == 1
    assert configs[0].platform == "ios"

    update_data = AppVersionUpdate(latest_build=25)
    updated = await update_version_config(
        platform="ios", update_data=update_data, svc=service, _current_user=MagicMock()
    )
    assert updated.platform == "ios"
