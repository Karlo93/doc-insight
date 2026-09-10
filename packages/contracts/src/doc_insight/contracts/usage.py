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
        """Count cached input once: cached_input_tokens is a subset of input_tokens."""
        return self.input_tokens + self.output_tokens


class UsageLedger(Protocol):
    def reserve(self, tenant: str, tokens: int, model: str) -> UUID:
        """Reserve tenant capacity before a call; reject requests exceeding the daily limit."""
        ...

    def settle(
        self, tenant: str, reservation: UUID, usage: TokenUsage | None, outcome: str
    ) -> None:
        """Settle once; None means unknown usage and charges the reserved amount."""
        ...

    def summary(self, tenant: str) -> dict[str, int]:
        """Return the current UTC-day accounting totals for this tenant."""
        ...


class BudgetExceeded(ValueError):
    """The tenant's UTC-day allowance cannot accommodate a new reservation."""
