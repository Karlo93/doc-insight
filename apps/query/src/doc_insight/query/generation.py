"""Select a generator per request without storing mutable provider reporting state."""

import json

import httpx
from doc_insight.contracts.query import Generation, GenerationInfo, Generator
from doc_insight.contracts.usage import BudgetExceeded, TokenUsage, UsageLedger
from doc_insight.query.extractive import ExtractiveGenerator
from doc_insight.query.openai_provider import ProviderFailure


class FallbackGenerator:
    """Prefer hosted output and report the provider used for this request.

    Missing primary or expected failures use local extraction. Unsupported hosted
    output is returned for abstention, not retried through the fallback.
    """

    def __init__(
        self,
        primary: Generator | None = None,
        model: str = "",
        ledger: UsageLedger | None = None,
        max_output: int = 700,
    ) -> None:
        self.primary, self.model = primary, model
        self.ledger, self.max_output = ledger, max_output
        self.fallback = ExtractiveGenerator()

    def generate(
        self, question: str, passages: list[str], *, tenant: str = ""
    ) -> tuple[Generation, GenerationInfo]:
        reason, usage = "disabled", None
        if self.primary is not None and passages:
            try:
                result = self._hosted(tenant, question, passages)
                return result, GenerationInfo(
                    provider="openai", model=self.model, usage=result.usage
                )
            except BudgetExceeded:
                reason = "daily_budget"
            except ProviderFailure as exc:
                reason, usage = exc.reason, exc.usage
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                reason = "provider_unavailable"
        return self.fallback.generate(question, passages), GenerationInfo(
            provider="extractive",
            model="sentence-window-v1",
            fallback_reason=reason,
            usage=usage,
        )

    def _hosted(self, tenant: str, question: str, passages: list[str]) -> Generation:
        if self.primary is None:
            raise ProviderFailure("disabled")
        # UTF-8 bytes bound text tokenization; allowance also covers instructions/schema.
        bound = (
            len(json.dumps([question, passages], ensure_ascii=False).encode())
            + 8192
            + self.max_output
        )
        reservation = (
            self.ledger.reserve(tenant, bound, self.model) if self.ledger else None
        )
        usage: TokenUsage | None = None
        outcome = "unknown"
        try:
            result = self.primary.generate(question, passages)
            usage, outcome = result.usage, "completed"
            return result
        except ProviderFailure as exc:
            usage, outcome = exc.usage, exc.reason
            raise
        except httpx.HTTPStatusError as exc:
            # A definitive client rejection did not run inference; timeouts remain unknown.
            if 400 <= exc.response.status_code < 500:
                usage, outcome = TokenUsage(), "rejected"
            raise
        finally:
            if reservation is not None and self.ledger is not None:
                self.ledger.settle(tenant, reservation, usage, outcome)
