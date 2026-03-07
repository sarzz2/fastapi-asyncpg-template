"""
Tests for background cleanup tasks, including log rotation and stagnant S3 file deletion.
"""

import os
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from api.tasks.delete_old_logs import delete_old_logs
from api.tasks.delete_s3_files import delete_stagnant_temporary_files


@pytest.fixture
def mock_s3() -> Any:
    """Provides a mocked S3 client for task testing."""
    with patch("api.tasks.delete_s3_files.s3_client") as mock:
        yield mock


@pytest.fixture
def mock_os() -> Any:
    """Provides a mocked OS module for file system task testing."""
    with patch("api.tasks.delete_old_logs.os") as mock:
        # Side effect to allow real path joining
        mock.path.join.side_effect = os.path.join
        yield mock


def test_log_cleanup_directory_missing(mock_os: MagicMock) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that the log cleanup task exits gracefully if the log directory does not exist.
    """
    mock_os.path.isdir.return_value = False
    delete_old_logs()
    mock_os.path.isdir.assert_called_once()
    mock_os.listdir.assert_not_called()


def test_log_cleanup_success(mock_os: MagicMock) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that old log files are correctly identified and deleted based on their date suffix.
    """
    mock_os.path.isdir.return_value = True
    mock_os.listdir.return_value = [
        "fastapi.log.2020-01-01",  # Stale
        "fastapi.log.2025-12-05",  # Fresh
        "fastapi.log",  # Active
        "random.txt",  # Irrelevant
    ]

    with patch("api.tasks.delete_old_logs.datetime") as mock_dt:
        # Mock 'now' to 2025-12-07
        mock_dt.now.return_value = datetime(2025, 12, 7)
        mock_dt.strptime.side_effect = datetime.strptime

        delete_old_logs()

        # Should only delete the 2020 log
        assert mock_os.remove.call_count == 1
        assert "fastapi.log.2020-01-01" in str(mock_os.remove.call_args[0][0])


def test_log_cleanup_ignores_malformed_filenames(mock_os: MagicMock) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that files with malformed date suffixes do not cause the log cleanup task to fail.
    """
    mock_os.path.isdir.return_value = True
    mock_os.listdir.return_value = ["fastapi.log.not-a-date"]

    with patch("api.tasks.delete_old_logs.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 12, 7)
        mock_dt.strptime.side_effect = ValueError("Format mismatch")

        delete_old_logs()
        mock_os.remove.assert_not_called()


def test_s3_cleanup_no_files(mock_s3: MagicMock) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that the S3 cleanup task handles empty buckets gracefully.
    """
    mock_s3.list_objects_v2.return_value = {}
    delete_stagnant_temporary_files()
    mock_s3.delete_object.assert_not_called()


def test_s3_cleanup_stagnant_files(mock_s3: MagicMock) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that only temporary files older than the threshold are deleted from S3.
    """
    with patch("api.tasks.delete_s3_files.datetime") as mock_dt:
        now = datetime(2025, 12, 7, 12, 0, 0)
        mock_dt.now.return_value = now

        # 1. Stale temp (20+ mins), 2. Fresh temp (5 mins), 3. Stale permanent (should remain)
        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "stale.tmp", "LastModified": datetime(2025, 12, 7, 11, 30, 0)},
                {"Key": "fresh.tmp", "LastModified": datetime(2025, 12, 7, 11, 55, 0)},
                {"Key": "stale.perm", "LastModified": datetime(2025, 12, 7, 11, 30, 0)},
            ]
        }

        def get_tags(**kwargs: str) -> dict:
            key = kwargs.get("Key", "")
            status_val = "permanent" if "perm" in key else "temporary"
            return {"TagSet": [{"Key": "status", "Value": status_val}]}

        mock_s3.get_object_tagging.side_effect = get_tags

        delete_stagnant_temporary_files()

        # Should only delete stale.tmp
        mock_s3.delete_object.assert_called_once()
        assert mock_s3.delete_object.call_args[1]["Key"] == "stale.tmp"


def test_s3_cleanup_handles_client_errors(mock_s3: MagicMock) -> None:  # pylint: disable=redefined-outer-name
    """
    Verify that S3 API errors do not crash the cleanup task.
    """
    mock_s3.list_objects_v2.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "ListObjectsV2"
    )

    # Should catch and log, not propagate
    delete_stagnant_temporary_files()
