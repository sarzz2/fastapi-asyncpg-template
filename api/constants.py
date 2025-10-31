from enum import Enum


class Environments(Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class TokenTypes(Enum):
    ACCESS = "access"
    REFRESH = "refresh"
    SUDO = "sudo"
