"""Validated process-wide gateway configuration."""

from functools import cache
from pathlib import Path
from typing import Self

from pydantic import Field, HttpUrl, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DI_")

    jwks_url: HttpUrl = HttpUrl("http://127.0.0.1:8000/.well-known/jwks.json")
    jwt_issuer: str = Field(default="doc-insight-dev", min_length=1)
    jwt_audience: str = Field(default="doc-insight", min_length=1)
    jwt_leeway_seconds: float = Field(default=30, ge=0, allow_inf_nan=False)
    jwks_cache_seconds: float = Field(default=300, gt=0, allow_inf_nan=False)
    jwks_refresh_seconds: float = Field(default=5, gt=0, allow_inf_nan=False)
    dev_jwks_path: Path | None = None
    redis_url: RedisDsn = RedisDsn("redis://127.0.0.1:6379/0")
    redis_timeout_seconds: float = Field(default=2, gt=0, allow_inf_nan=False)
    rate_limit_rps: float = Field(default=5, gt=0, allow_inf_nan=False)
    rate_limit_burst: int = Field(default=10, ge=1)
    rate_limit_fail_open: bool = False
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    max_upstream_response_bytes: int = Field(default=16 * 1024 * 1024, ge=1)
    ingest_url: HttpUrl = HttpUrl("http://127.0.0.1:8001")
    query_url: HttpUrl = HttpUrl("http://127.0.0.1:8002")
    upstream_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    cors_origins: str = ""
    gateway_host: str = "127.0.0.1"
    gateway_port: int = Field(default=8000, ge=1, le=65535)

    @model_validator(mode="after")
    def cache_covers_refresh_cooldown(self) -> Self:
        if self.jwks_cache_seconds < self.jwks_refresh_seconds:
            raise ValueError("JWKS cache lifetime must cover the refresh interval")
        return self

    @field_validator("dev_jwks_path", mode="before")
    @classmethod
    def optional_path(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("cors_origins")
    @classmethod
    def explicit_origins(cls, value: str) -> str:
        for origin in filter(None, value.split(",")):
            url = HttpUrl(origin.strip())
            if url.path != "/" or url.query or url.fragment or url.username:
                raise ValueError("CORS requires explicit HTTP origins")
            if url.host == "*":
                raise ValueError("CORS requires explicit HTTP origins")
        return value


@cache
def get_settings() -> Settings:
    return Settings()
