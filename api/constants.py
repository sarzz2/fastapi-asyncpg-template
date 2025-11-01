from enum import Enum


class Environments(Enum):
    """Application Environments Constants"""

    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class TokenTypes(Enum):
    """Token Types Constants"""

    ACCESS = "access"
    REFRESH = "refresh"
    SUDO = "sudo"
