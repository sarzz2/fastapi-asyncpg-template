from unittest.mock import MagicMock, patch

from starlette.requests import Request

from api.core.rate_limit import get_real_user_key


def test_get_real_user_key_bearer() -> None:
    """Test identifying user by Bearer token."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"Authorization": "Bearer some-token"}

    key = get_real_user_key(mock_request)
    assert key == "Bearer some-token"


def test_get_real_user_key_basic_fallback() -> None:
    """Test that non-Bearer auth falls back to IP."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"Authorization": "Basic user:pass"}

    # Mock get_remote_address since it's called in fallback
    with patch("api.core.rate_limit.get_remote_address", return_value="127.0.0.1") as patch_remote_addr:
        key = get_real_user_key(mock_request)

        assert key == "127.0.0.1"
        patch_remote_addr.assert_called_once_with(mock_request)


def test_get_real_user_key_no_auth() -> None:
    """Test that missing auth falls back to IP."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}

    with patch("api.core.rate_limit.get_remote_address", return_value="127.0.0.1"):
        key = get_real_user_key(mock_request)
        assert key == "127.0.0.1"
