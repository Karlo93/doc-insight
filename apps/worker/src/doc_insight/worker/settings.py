"""Process-wide configuration; only settings needed by extraction exist in M1."""

from functools import cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DI_")

    ocr_min_chars: int = Field(default=20, ge=0)
    ocr_dpi: int = Field(default=200, gt=0)
    ocr_langs: str = "eng+hrv"
    tesseract_cmd: str = "tesseract"


@cache
def get_settings() -> Settings:
    return Settings()
