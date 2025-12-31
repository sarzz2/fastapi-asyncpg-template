from typing import Callable

from flagsmith import Flagsmith

from api.core.config import settings


class FeatureFlagService:
    """Singleton service to manage feature flags"""

    _instance = None

    def __init__(self) -> None:
        self.client: Flagsmith | None
        if settings.FLAGSMITH_ENVIRONMENT_KEY:
            self.client = Flagsmith(environment_key=settings.FLAGSMITH_ENVIRONMENT_KEY)
        else:
            self.client = None

    @classmethod
    def get_instance(cls) -> "FeatureFlagService":
        """Get the singleton instance of the service"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def is_enabled(self, feature_name: str, identity: str = None, traits: dict = None) -> bool:
        """Check if a feature is enabled, optionally for a specific identity with traits"""
        if not self.client:
            # Fallback if no key is configured (e.g. local dev without keys)
            return False
        try:
            if identity:
                flags = self.client.get_identity_flags(identifier=identity, traits=traits)
            else:
                flags = self.client.get_environment_flags()
            return flags.is_feature_enabled(feature_name)
        except Exception:  # pylint: disable=broad-except
            return False


feature_flag_service = FeatureFlagService.get_instance()


def feature_enabled(feature_name: str, identity: str = None, traits: dict = None) -> Callable[[], bool]:
    """
    Dependency factory to check if a feature is enabled.
    Usage: Depends(feature_enabled("my_feature", identity="user_123", traits={"role": "beta"}))
    """

    def check_flag() -> bool:
        return feature_flag_service.is_enabled(feature_name, identity=identity, traits=traits)

    return check_flag
