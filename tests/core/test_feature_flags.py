from unittest.mock import MagicMock, patch

from api.core.feature_flags import FeatureFlagService, feature_enabled


def test_is_enabled_true() -> None:
    """Test that is_enabled returns True when the feature is enabled"""
    mock_client = MagicMock()
    mock_flags = MagicMock()
    mock_flags.is_feature_enabled.return_value = True
    mock_client.get_environment_flags.return_value = mock_flags

    with patch("api.core.feature_flags.Flagsmith", return_value=mock_client):
        # We need to reset the singleton for the test or patch the instance
        # simpler to patch the instance on the module or the class

        service = FeatureFlagService()
        service.client = mock_client  # manually inject mock

        assert service.is_enabled("test_feature") is True
        mock_flags.is_feature_enabled.assert_called_with("test_feature")


def test_is_enabled_false() -> None:
    """Test that is_enabled returns False when the feature is disabled"""
    mock_client = MagicMock()
    mock_flags = MagicMock()
    mock_flags.is_feature_enabled.return_value = False
    mock_client.get_environment_flags.return_value = mock_flags

    service = FeatureFlagService()
    service.client = mock_client

    assert service.is_enabled("test_feature") is False


def test_is_enabled_with_identity() -> None:
    """Test that is_enabled returns True when the feature is enabled for a specific identity"""
    mock_client = MagicMock()
    mock_flags = MagicMock()
    mock_flags.is_feature_enabled.return_value = True
    mock_client.get_identity_flags.return_value = mock_flags

    service = FeatureFlagService()
    service.client = mock_client

    # Check with identity
    assert service.is_enabled("test_feature", identity="user_123") is True
    # Verify we called the identity method, not the environment one
    mock_client.get_identity_flags.assert_called_with(identifier="user_123", traits=None)
    mock_flags.is_feature_enabled.assert_called_with("test_feature")


def test_is_enabled_with_traits() -> None:
    """Test that is_enabled returns True when the feature is enabled for a specific identity with traits"""
    mock_client = MagicMock()
    mock_flags = MagicMock()
    mock_flags.is_feature_enabled.return_value = True
    mock_client.get_identity_flags.return_value = mock_flags

    service = FeatureFlagService()
    service.client = mock_client

    traits = {"role": "beta_tester"}
    assert service.is_enabled("test_feature", identity="user_123", traits=traits) is True

    mock_client.get_identity_flags.assert_called_with(identifier="user_123", traits=traits)


def test_is_enabled_exception_fallback() -> None:
    """Test that is_enabled returns False when the feature is enabled for a specific identity with traits"""
    mock_client = MagicMock()
    mock_client.get_environment_flags.side_effect = Exception("Connection error")

    service = FeatureFlagService()
    service.client = mock_client

    assert service.is_enabled("test_feature") is False


def test_dependency_enabled() -> None:
    """Test that the dependency returns True when the feature is enabled"""
    with patch("api.core.feature_flags.feature_flag_service") as mock_service:
        mock_service.is_enabled.return_value = True

        # Get the dependency callable
        dependency = feature_enabled("test_feature")

        # Invoke it
        result = dependency()

        assert result is True
        mock_service.is_enabled.assert_called_with("test_feature", identity=None, traits=None)


def test_dependency_with_traits() -> None:
    """Test that the dependency returns True when the feature is enabled for a specific identity with traits"""
    with patch("api.core.feature_flags.feature_flag_service") as mock_service:
        mock_service.is_enabled.return_value = True

        # Get the dependency callable with args
        traits = {"role": "beta"}
        dependency = feature_enabled("test_feature", identity="user_123", traits=traits)

        # Invoke it
        result = dependency()

        assert result is True
        mock_service.is_enabled.assert_called_with("test_feature", identity="user_123", traits=traits)
