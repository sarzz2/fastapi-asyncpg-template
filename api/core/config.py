from pydantic.v1 import BaseSettings

from api.constants import Environments


class Settings(BaseSettings):
    PROJECT_NAME: str = "Influmatch"
    PROJECT_VERSION: str = "0.1.0"
    API_V0_STR: str = "/api/v0"
    SECRET_KEY: str = "test_secret_key"
    DOMAIN: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3OO0"
    ENV: str = Environments.DEV.value

    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 336
    REFRESH_TOKEN_EXPIRE_DAYS: int = 21
    SUDO_TOKEN_EXPIRE_MINUTES: int = 60

    PRIMARY_DATABASE_URL: str = "postgresql://user:password@localhost/influmatch"
    REPLICA_DATABASE_URL: str = "postgresql://user:password@localhost/influmatch"
    TEST_DATABASE_URL: str = "postgresql://user:password@localhost/test_influmatch"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    ADMIN_EMAIL: str = "admin@admin.com"
    ADMIN_PASSWORD: str = "admin"
    # default values for localstack
    S3_ENDPOINT_URL: str = "http://localhost:4566"
    S3_REGION_NAME: str = "us-east-1"
    AWS_ACCESS_KEY: str = "test"
    AWS_SECRET_ACCESS_KEY: str = "test"
    AWS_BUCKET_NAME: str = "my-bucket"

    class Config:
        env_file = ".env"


settings = Settings()
