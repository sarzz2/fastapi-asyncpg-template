from pydantic_settings import BaseSettings, SettingsConfigDict

from api.constants import Environments


class Settings(BaseSettings):
    """Application Settings Constants"""

    PROJECT_NAME: str = "Influmatch"
    PROJECT_VERSION: str = "0.1.0"
    API_V0_STR: str = "/api/v0"
    SECRET_KEY: str = "test_secret_key"
    DOMAIN: str = "http://127.0.0.1:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    ENV: str = Environments.DEV.value
    USE_JSON_LOGS: bool = False
    SENTRY_DSN: str | None = None

    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 336
    REFRESH_TOKEN_EXPIRE_DAYS: int = 21
    SUDO_TOKEN_EXPIRE_MINUTES: int = 60

    PRIMARY_DATABASE_URL: str = "postgresql://user:password@localhost/influmatch"
    REPLICA_DATABASE_URL: str = "postgresql://user:password@localhost/influmatch"
    TEST_DATABASE_URL: str = "postgresql://user:password@localhost/test_influmatch"
    MIN_CONNECTION_COUNT: int = 1
    MAX_CONNECTION_COUNT: int = 10
    HEALTH_CHECK_INTERVAL: int = 30  # in seconds
    REGION_PRIORITY: list[str] = []

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # default values for localstack
    S3_ENDPOINT_URL: str = "http://localhost:4566"
    S3_REGION_NAME: str = "us-east-1"
    AWS_ACCESS_KEY: str = "test"
    AWS_SECRET_ACCESS_KEY: str = "test"
    AWS_BUCKET_NAME: str = "my-bucket"

    # google oauth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
    ]

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")


settings = Settings()
