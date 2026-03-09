# pylint: disable=redefined-outer-name
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException, status

from api.apps.s3.v0.routes.s3 import delete_file, generate_upload_url, get_file
from api.apps.s3.v0.schemas.s3 import S3UploadUrlRequest
from api.apps.s3.v0.services.s3 import S3Service, get_s3_service


@pytest.fixture
def s3_service() -> S3Service:
    """Fixture for S3Service."""
    return S3Service()


def test_generate_presigned_url(s3_service: S3Service) -> None:
    """
    Test generate_presigned_url method.
    Args:
        s3_service: S3Service fixture
    """
    with patch("api.apps.s3.v0.services.s3.s3_client") as mock_client:
        mock_client.generate_presigned_post.return_value = {
            "url": "http://s3.amazonaws.com/bucket",
            "fields": {"key": "value"},
        }

        result = s3_service.generate_presigned_url("test.jpg", "image/jpeg")

        assert result["upload_url"] == "http://s3.amazonaws.com/bucket"
        assert "key" in result
        assert result["fields"] == {"key": "value"}
        mock_client.generate_presigned_post.assert_called_once()


def test_generate_presigned_url_error(s3_service: S3Service) -> None:
    """
    Test generate_presigned_url method with error.
    Args:
        s3_service: S3Service fixture
    """
    with patch("api.apps.s3.v0.services.s3.s3_client") as mock_client:
        mock_client.generate_presigned_post.side_effect = ClientError({}, "GeneratePresignedPost")

        with pytest.raises(ClientError):
            s3_service.generate_presigned_url("test.jpg")


def test_delete_file(s3_service: S3Service) -> None:
    """
    Test delete_file method.
    Args:
        s3_service: S3Service fixture
    """
    with patch("api.apps.s3.v0.services.s3.s3_client") as mock_client:
        s3_service.delete_file("test_key")
        mock_client.delete_object.assert_called_once_with(Bucket=s3_service.bucket_name, Key="test_key")


def test_delete_file_error(s3_service: S3Service) -> None:
    """
    Test delete_file method with error.
    Args:
        s3_service: S3Service fixture
    """
    with patch("api.apps.s3.v0.services.s3.s3_client") as mock_client:
        mock_client.delete_object.side_effect = ClientError({}, "DeleteObject")

        with pytest.raises(ClientError):
            s3_service.delete_file("test_key")


def test_get_file_url_presigned(s3_service: S3Service) -> None:
    """
    Test get_file_url method with presigned.
    Args:
        s3_service: S3Service fixture
    """
    with patch("api.apps.s3.v0.services.s3.s3_client") as mock_client:
        mock_client.generate_presigned_url.return_value = "http://presigned.url"

        url = s3_service.get_file_url("test_key", presigned=True)
        assert url == "http://presigned.url"


def test_get_file_url_presigned_error(s3_service: S3Service) -> None:
    """
    Test get_file_url method with presigned and error.
    Args:
        s3_service: S3Service fixture
    """
    with patch("api.apps.s3.v0.services.s3.s3_client") as mock_client:
        mock_client.generate_presigned_url.side_effect = ClientError({}, "GeneratePresignedUrl")

        url = s3_service.get_file_url("test_key", presigned=True)
        assert url == ""


def test_get_file_url_public_localhost(s3_service: S3Service) -> None:
    """
    Test get_file_url method with public and localhost.
    Args:
        s3_service: S3Service fixture
    """
    s3_service.endpoint_url = "http://localhost:4566"
    url = s3_service.get_file_url("test_key", presigned=False)
    assert url == f"http://localhost:4566/{s3_service.bucket_name}/test_key"


def test_get_file_url_public_aws(s3_service: S3Service) -> None:
    """
    Test get_file_url method with public and aws.
    Args:
        s3_service: S3Service fixture
    """
    s3_service.endpoint_url = "https://s3.amazonaws.com"
    url = s3_service.get_file_url("test_key", presigned=False)
    assert url == f"https://{s3_service.bucket_name}.s3.{s3_service.region_name}.amazonaws.com/test_key"


# --- Route Tests ---


@pytest.mark.asyncio
async def test_route_generate_upload_url() -> None:
    """
    Test generate_upload_url route.
    """
    mock_service = MagicMock()
    mock_service.generate_presigned_url.return_value = {
        "upload_url": "http://url",
        "fields": {},
        "key": "key",
        "expires_in": 300,
    }

    request = S3UploadUrlRequest(filename="test.jpg", content_type="image/jpeg")
    response = await generate_upload_url(request, s3_service=mock_service, _current_user=MagicMock())

    assert response.upload_url == "http://url"
    mock_service.generate_presigned_url.assert_called_once()


@pytest.mark.asyncio
async def test_route_generate_upload_url_error() -> None:
    """
    Test generate_upload_url route with error.
    """
    mock_service = MagicMock()
    mock_service.generate_presigned_url.side_effect = Exception("Error")

    request = S3UploadUrlRequest(filename="test.jpg", content_type="image/jpeg")

    with pytest.raises(HTTPException) as exc:
        await generate_upload_url(request, s3_service=mock_service, _current_user=MagicMock())

    assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_route_delete_file() -> None:
    """
    Test delete_file route.
    """
    mock_service = MagicMock()

    await delete_file(key="test_key", s3_service=mock_service, _current_user=MagicMock())

    mock_service.delete_file.assert_called_once_with("test_key")


@pytest.mark.asyncio
async def test_route_delete_file_error() -> None:
    """
    Test delete_file route with error.
    """
    mock_service = MagicMock()
    mock_service.delete_file.side_effect = Exception("Error")

    with pytest.raises(HTTPException) as exc:
        await delete_file(key="test_key", s3_service=mock_service, _current_user=MagicMock())

    assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_route_get_file() -> None:
    """
    Test get_file route.
    """
    mock_service = MagicMock()
    mock_service.get_file_url.return_value = "http://url"

    url = await get_file(key="test_key", s3_service=mock_service)

    assert url == "http://url"
    mock_service.get_file_url.assert_called_once_with("test_key")


@pytest.mark.asyncio
async def test_route_get_file_error() -> None:
    """
    Test get_file route with error.
    """
    mock_service = MagicMock()
    mock_service.get_file_url.side_effect = Exception("Error")

    with pytest.raises(HTTPException) as exc:
        await get_file(key="test_key", s3_service=mock_service)

    assert exc.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_get_s3_service_dependency() -> None:
    """
    Test get_s3_service dependency.
    """

    service = await get_s3_service()
    assert isinstance(service, S3Service)
