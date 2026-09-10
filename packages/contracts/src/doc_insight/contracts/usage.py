"""Accounting contracts contain metadata only, never prompts or credentials."""

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    request_id: str | None = None

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class UsageLedger(Protocol):
    def reserve(self, tenant: str, tokens: int, model: str) -> UUID: ...
    def settle(
        self, tenant: str, reservation: UUID, usage: TokenUsage | None, outcome: str
    ) -> None: ...
    def summary(self, tenant: str) -> dict[str, int]: ...


class BudgetExceeded(ValueError):
    """The tenant's UTC-day allowance cannot accommodate a new reservation."""
