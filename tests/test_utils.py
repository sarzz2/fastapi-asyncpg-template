# pylint: disable=duplicate-code  # Similar user-registration setup is shared across test files by design

"""
Tests for shared utility functions.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from api.utils.date import get_utc_now
from api.utils.pydantic_utils import generate_file_url


def test_generate_file_url_with_s3() -> None:
    """
    Verify that S3 file URLs are generated correctly when a key is provided.
    """
    with patch("api.utils.pydantic_utils._s3_service") as mock_s3:
        mock_s3.get_file_url.return_value = "https://s3.amazonaws.com/test-key"

        # 1. Valid Key
        assert generate_file_url("test-key") == "https://s3.amazonaws.com/test-key"
        mock_s3.get_file_url.assert_called_with("test-key", presigned=True)

        # 2. Empty/None cases
        assert generate_file_url(None) is None
        assert generate_file_url("") is None


def test_get_low_latency_utc_now() -> None:
    """
    Verify that get_utc_now returns a localized UTC datetime with acceptable drift.
    """
    now = get_utc_now()
    assert now.tzinfo == timezone.utc

    # Drift check (should be negligible)
    drift = datetime.now(timezone.utc) - now
    assert abs(drift.total_seconds()) < 0.1
