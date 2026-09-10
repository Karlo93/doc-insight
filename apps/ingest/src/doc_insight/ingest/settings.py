"""Validated configuration, cached once per process."""

from functools import cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DI_")

    database_url: str = "postgresql+psycopg://di_app:di_app@localhost:5432/di"
    s3_endpoint: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "documents"
    s3_access_key: SecretStr = Field(...)
    s3_secret_key: SecretStr = Field(...)
    s3_use_ssl: bool = False
    redis_url: str = "redis://localhost:6379/0"
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    relay_poll_seconds: float = Field(default=1, gt=0)
    relay_batch: int = Field(default=100, ge=1, le=10000)
    # Containers bind every interface; the local default stays loopback-only.
    http_host: str = Field(default="127.0.0.1", min_length=1)
    http_port: int = Field(default=8001, ge=1, le=65535)


@cache
def get_settings() -> Settings:
    # Required credentials come from the environment, not constructor arguments.
    return Settings()  # type: ignore[call-arg]
