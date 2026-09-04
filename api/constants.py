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


class AdminConstants:
    """Admin portal default settings and display constants."""

    DEFAULT_PAGE_SIZE = 50
    DEFAULT_PAGE_SIZE_OPTIONS = [10, 25, 50, 100, 200]
    DEFAULT_ADDITIONAL_CSS_LINKS = ["/admin/static/css/admin_custom.css"]
    DEFAULT_DISPLAY_KEYS = ("name", "title", "label", "username", "email")
    SUPPORTED_LANGUAGES = ["en", "es", "fr", "de", "ja"]
    SUPPORTED_TIMEZONES = [
        "UTC",
        "Asia/Kolkata",
        "America/New_York",
        "Europe/London",
        "Asia/Tokyo",
    ]
