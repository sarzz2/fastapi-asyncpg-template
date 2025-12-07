"""Tests for utility functions."""

from datetime import datetime, timezone
from unittest.mock import patch

from api.utils.date import get_utc_now
from api.utils.pydantic_utils import generate_file_url


def test_generate_file_url() -> None:
    """Test generate_file_url."""
    with patch("api.utils.pydantic_utils._s3_service") as mock_s3:
        mock_s3.get_file_url.return_value = "http://url"

        # Test with key
        assert generate_file_url("key") == "http://url"
        mock_s3.get_file_url.assert_called_with("key", presigned=True)

        # Test without key
        assert generate_file_url(None) is None
        assert generate_file_url("") is None


def test_get_utc_now() -> None:
    """Test get_utc_now."""
    now = get_utc_now()
    assert now.tzinfo == timezone.utc
    # Tolerance check
    diff = datetime.now(timezone.utc) - now
    assert abs(diff.total_seconds()) < 1.0
