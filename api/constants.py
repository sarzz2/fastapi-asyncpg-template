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


class RequestHeaders(Enum):
    """Common Request Headers"""

    APP_VERSION = "X-App-Version"
    APP_BUILD = "X-App-Build"
    PLATFORM = "X-Platform"
    DEVICE_ID = "X-Device-Id"
