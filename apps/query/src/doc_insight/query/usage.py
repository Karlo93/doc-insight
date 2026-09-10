"""Atomic UTC-day budgets survive process concurrency, restarts and ambiguous calls."""

from uuid import UUID, uuid4

from doc_insight.contracts.usage import BudgetExceeded, TokenUsage
from doc_insight.worker.uploads import set_tenant
from sqlalchemy import Engine, text


class PostgresUsageLedger:
    def __init__(self, engine: Engine, limit: int):
        self.engine, self.limit = engine, limit

    def reserve(self, tenant: str, tokens: int, model: str) -> UUID:
        """Atomically reserve UTC-day capacity or raise BudgetExceeded before inference."""
        if tokens < 1 or tokens > self.limit:
            raise BudgetExceeded("daily_budget")
        identifier = uuid4()
        with self.engine.begin() as connection:
            set_tenant(connection, tenant)
            # The conditional upsert serializes competing reservations for the same day.
            row = connection.execute(
                text("""
                INSERT INTO llm_budgets (tenant_id, day, reserved) VALUES (:tenant, (clock_timestamp() AT TIME ZONE 'UTC')::date, :tokens)
                ON CONFLICT (tenant_id, day) DO UPDATE
                SET reserved = llm_budgets.reserved + :tokens
                WHERE llm_budgets.charged + llm_budgets.reserved + :tokens <= :limit
                RETURNING day
            """),
                {"tenant": tenant, "tokens": tokens, "limit": self.limit},
            ).first()
            if row is None:
                raise BudgetExceeded("daily_budget")
            connection.execute(
                text("""INSERT INTO llm_usage
                (id, tenant_id, day, model, reserved_tokens)
                VALUES (:id, :tenant, :day, :model, :tokens)"""),
                {
                    "id": identifier,
                    "tenant": tenant,
                    "day": row.day,
                    "model": model,
                    "tokens": tokens,
                },
            )
        return identifier

    def settle(
        self, tenant: str, reservation: UUID, usage: TokenUsage | None, outcome: str
    ) -> None:
        """Unknown usage charges the whole reservation; repeated settlement is a no-op."""
        actual = usage or TokenUsage()
        with self.engine.begin() as connection:
            set_tenant(connection, tenant)
            row = connection.execute(
                text("""UPDATE llm_usage SET
                input_tokens=:input, output_tokens=:output, cached_input_tokens=:cached,
                request_id=:request, outcome=:outcome
                WHERE id=:id AND tenant_id=:tenant AND outcome='reserved'
                RETURNING day, reserved_tokens"""),
                {
                    "id": reservation,
                    "tenant": tenant,
                    "input": actual.input_tokens,
                    "output": actual.output_tokens,
                    "cached": actual.cached_input_tokens,
                    "request": actual.request_id,
                    "outcome": outcome,
                },
            ).first()
            if row is None:
                return
            connection.execute(
                text("""UPDATE llm_budgets
                SET reserved=reserved-:reserved, charged=charged+:charged
                WHERE tenant_id=:tenant AND day=:day"""),
                {
                    "tenant": tenant,
                    "day": row.day,
                    "reserved": row.reserved_tokens,
                    "charged": usage.total
                    if usage is not None
                    else row.reserved_tokens,
                },
            )

    def summary(self, tenant: str) -> dict[str, int]:
        """Report current UTC-day charges, outstanding reservations and provider counts."""
        with self.engine.begin() as connection:
            set_tenant(connection, tenant)
            budget = connection.execute(
                text("""SELECT charged, reserved FROM llm_budgets
                WHERE tenant_id=:tenant AND day=(clock_timestamp() AT TIME ZONE 'UTC')::date"""),
                {"tenant": tenant},
            ).first()
            usage = connection.execute(
                text("""SELECT count(*) AS requests,
                coalesce(sum(input_tokens),0) AS input, coalesce(sum(output_tokens),0) AS output,
                coalesce(sum(cached_input_tokens),0) AS cached FROM llm_usage
                WHERE tenant_id=:tenant AND day=(clock_timestamp() AT TIME ZONE 'UTC')::date"""),
                {"tenant": tenant},
            ).one()
            return {
                "daily_limit": self.limit,
                "charged_tokens": int(budget.charged) if budget else 0,
                "reserved_tokens": int(budget.reserved) if budget else 0,
                "requests": int(usage.requests),
                "input_tokens": int(usage.input),
                "output_tokens": int(usage.output),
                "cached_input_tokens": int(usage.cached),
            }
