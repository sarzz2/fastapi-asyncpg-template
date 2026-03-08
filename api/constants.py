from enum import Enum


class Environments(Enum):
    """Application Environments Constants"""

    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"
    TEST = "test"


class TokenTypes(Enum):
    """Token Types Constants"""

    ACCESS = "access"
    REFRESH = "refresh"
    SUDO = "sudo"


class OAuthProviders(Enum):
    """OAuth Providers Constants"""

    GOOGLE = "google"
    FACEBOOK = "facebook"
    GITHUB = "github"
