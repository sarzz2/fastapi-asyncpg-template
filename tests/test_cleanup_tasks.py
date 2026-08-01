"""
Tests for background cleanup tasks, including log rotation.
"""

import os
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from api.tasks.delete_old_logs import delete_old_logs


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
