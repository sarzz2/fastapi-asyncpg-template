"""Tests for Celery tasks."""
# pylint: disable=redefined-outer-name, no-value-for-parameter, unused-argument

import os
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from api.tasks.delete_old_logs import delete_old_logs
from api.tasks.delete_s3_files import delete_stagnant_temporary_files


@pytest.fixture
def mock_s3_client() -> Any:
    """Mock s3_client."""
    with patch("api.tasks.delete_s3_files.s3_client") as mock:
        yield mock


@pytest.fixture
def mock_os() -> Any:
    """Mock os module."""
    with patch("api.tasks.delete_old_logs.os") as mock:
        yield mock


def test_delete_old_logs_no_dir(mock_os: MagicMock) -> None:
    """Test delete_old_logs when the log directory does not exist."""
    mock_os.path.isdir.return_value = False

    # Call the task (simulating the celery task call)
    delete_old_logs()

    # Should check if dir exists
    mock_os.path.isdir.assert_called_once()
    # Should not list dir or remove anything
    mock_os.listdir.assert_not_called()
    mock_os.remove.assert_not_called()


def test_delete_old_logs_success(mock_os: MagicMock) -> None:
    """Test delete_old_logs successfully deletes old files."""
    mock_os.path.isdir.return_value = True
    # Use real os.path.join so we get a string path, not a Mock
    mock_os.path.join.side_effect = os.path.join

    # Setup mock files
    # old file, new file, active log file, malformed file
    files = [
        "fastapi.log.2023-01-01",  # Very old
        "fastapi.log.2025-12-01",  # Recent (relative to "now")
        "fastapi.log",  # Active
        "fastapi.log.malformed",  # Malformed
        "other.log",  # Irrelevant
    ]
    mock_os.listdir.return_value = files

    # We need to mock datetime in the module to control "now"
    # The module uses: cutoff_date = datetime.now() - timedelta(days=30)
    # Let's say "now" is 2025-12-07. 30 days ago is 2025-11-07.
    # 2023-01-01 is OLD.
    # 2025-12-01 is NEW.

    # Since we can't easily mock built-in datetime.datetime directly if it's imported as `from datetime import datetime`
    # without some libraries like freezegun, but we can patch the import in the module.
    # The module has `from datetime import datetime, timedelta`.
    # We patch `api.tasks.delete_old_logs.datetime`.

    with patch("api.tasks.delete_old_logs.datetime") as mock_datetime:
        # Mock now() to return a fixed date
        fixed_now = datetime(2025, 12, 7)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.strptime.side_effect = datetime.strptime  # Pass through strptime

        delete_old_logs()

        # Verify os.remove was called ONLY for the old file
        # Expected path construction relies on LOGS_DIR import, but we can just check the call args relatively
        # or verify the number of calls.

        assert mock_os.remove.call_count == 1
        # Get the argument passed to remove
        call_args = mock_os.remove.call_args[0][0]
        assert "fastapi.log.2023-01-01" in str(call_args)


def test_delete_old_logs_invalid_date(mock_os: MagicMock) -> None:
    """Test handling of files that match pattern but have invalid dates."""
    mock_os.path.isdir.return_value = True
    mock_os.listdir.return_value = ["fastapi.log.NotADate"]

    # We don't strictly need to mock datetime here if we just rely on exception catching,
    # but to be safe and deterministic:
    with patch("api.tasks.delete_old_logs.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2025, 12, 7)
        mock_datetime.strptime.side_effect = ValueError("Invalid date")

        delete_old_logs()

        mock_os.remove.assert_not_called()


def test_delete_stagnant_no_files(mock_s3_client: MagicMock) -> None:
    """Test delete_stagnant_temporary_files with no files."""
    mock_s3_client.list_objects_v2.return_value = {}  # No 'Contents'

    delete_stagnant_temporary_files()

    mock_s3_client.delete_object.assert_not_called()


def test_delete_stagnant_success(mock_s3_client: MagicMock) -> None:
    """Test deletion of stagnant temporary files."""
    # Mock datetime to control "now"
    # Module uses `datetime.now(last_modified.tzinfo)`

    with patch("api.tasks.delete_s3_files.datetime") as mock_datetime:
        now = datetime(2025, 12, 7, 12, 0, 0)
        mock_datetime.now.return_value = now

        # Setup S3 response
        # 1. Stagnant temp file (Modified 12:00 - 20 mins = 11:40)
        # 2. Fresh temp file (Modified 12:00 - 5 mins = 11:55)
        # 3. Perm file (Status != temporary)

        files = [
            {"Key": "stagnant.jpg", "LastModified": datetime(2025, 12, 7, 11, 40, 0)},
            {"Key": "fresh.jpg", "LastModified": datetime(2025, 12, 7, 11, 55, 0)},
            {"Key": "permanent.jpg", "LastModified": datetime(2025, 12, 7, 11, 0, 0)},
        ]

        mock_s3_client.list_objects_v2.return_value = {"Contents": files}

        # Mock get_object_tagging
        def get_tags(Bucket: str, Key: str) -> dict[str, Any]:
            if Key == "stagnant.jpg":
                return {"TagSet": [{"Key": "status", "Value": "temporary"}]}
            if Key == "fresh.jpg":
                return {"TagSet": [{"Key": "status", "Value": "temporary"}]}
            if Key == "permanent.jpg":
                return {"TagSet": [{"Key": "status", "Value": "permanent"}]}
            return {"TagSet": []}

        mock_s3_client.get_object_tagging.side_effect = get_tags

        delete_stagnant_temporary_files()

        # Should delete only stagnant.jpg
        mock_s3_client.delete_object.assert_called_once()
        call_kwargs = mock_s3_client.delete_object.call_args[1]
        assert call_kwargs["Key"] == "stagnant.jpg"


def test_delete_stagnant_files_client_error(mock_s3_client: MagicMock) -> None:
    """Test error handling in s3 task."""
    mock_s3_client.list_objects_v2.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "ListObjectsV2"
    )

    # Should catch exception and log error, not crash
    delete_stagnant_temporary_files()
    # Pass if no exception raised
