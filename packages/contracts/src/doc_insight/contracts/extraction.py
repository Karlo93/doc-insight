"""The file-to-text boundary; counts are derived so they cannot drift from text."""

from typing import Literal

from pydantic import BaseModel, Field, computed_field

MediaType = Literal["application/pdf", "image/png", "image/jpeg", "image/tiff"]
PIPELINE_VERSION = "6"


class Page(BaseModel):
    number: int = Field(ge=1)
    text: str
    source: Literal["text_layer", "ocr"]
    language: str = "und"
    confidence: float = Field(default=0, ge=0, le=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def char_count(self) -> int:
        return len(self.text)


class ExtractedDocument(BaseModel):
    pipeline_version: str = PIPELINE_VERSION
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: MediaType
    pages: list[Page]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def page_count(self) -> int:
        return len(self.pages)
