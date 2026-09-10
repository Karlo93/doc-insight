"""Deterministic, single-day usage ledger for provider contract tests."""

from threading import Lock
from uuid import UUID, uuid4

from doc_insight.contracts.usage import BudgetExceeded, TokenUsage


class InMemoryUsageLedger:
    def __init__(self, limit: int):
        self.limit = limit
        self.lock = Lock()
        self.entries: dict[UUID, tuple[str, int, TokenUsage | None, str]] = {}

    def _summary(self, tenant: str) -> dict[str, int]:
        rows = [entry for entry in self.entries.values() if entry[0] == tenant]
        return {
            "daily_limit": self.limit,
            "charged_tokens": sum(
                usage.total if usage else tokens
                for _, tokens, usage, state in rows
                if state != "reserved"
            ),
            "reserved_tokens": sum(
                tokens for _, tokens, _, state in rows if state == "reserved"
            ),
            "requests": len(rows),
            "input_tokens": sum(usage.input_tokens for _, _, usage, _ in rows if usage),
            "output_tokens": sum(
                usage.output_tokens for _, _, usage, _ in rows if usage
            ),
            "cached_input_tokens": sum(
                usage.cached_input_tokens for _, _, usage, _ in rows if usage
            ),
        }

    def reserve(self, tenant: str, tokens: int, model: str) -> UUID:
        with self.lock:
            summary = self._summary(tenant)
            if (
                tokens < 1
                or summary["charged_tokens"] + summary["reserved_tokens"] + tokens
                > self.limit
            ):
                raise BudgetExceeded("daily_budget")
            identifier = uuid4()
            self.entries[identifier] = (tenant, tokens, None, "reserved")
            return identifier

    def settle(
        self, tenant: str, reservation: UUID, usage: TokenUsage | None, outcome: str
    ) -> None:
        with self.lock:
            row = self.entries.get(reservation)
            if row and row[0] == tenant and row[3] == "reserved":
                self.entries[reservation] = (tenant, row[1], usage, outcome)

    def summary(self, tenant: str) -> dict[str, int]:
        with self.lock:
            return self._summary(tenant)
