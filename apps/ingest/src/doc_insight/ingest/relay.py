"""At-least-once publishing with transaction-held row locks."""

from threading import Event

from doc_insight.contracts.ingest import DocumentUploaded, EventPublisher
from doc_insight.observability import extract, inject, stage
from doc_insight.worker.uploads import set_tenant
from opentelemetry.context import attach, detach
from sqlalchemy import Engine, MetaData, Table, func, select


class OutboxRelay:
    """Publish one tenant's outbox while holding skip-locked transaction row locks.

    Publication precedes the SQL marker. A crash or rollback can publish the same
    event again, so consumers must tolerate at-least-once delivery.
    """

    def __init__(self, engine: Engine, publisher: EventPublisher) -> None:
        self.engine, self.publisher = engine, publisher
        self.outbox = Table("outbox", MetaData(), autoload_with=engine)

    def run_once(self, tenant_id: str, batch: int = 100) -> int:
        if batch < 1:
            raise ValueError("Batch must be positive")
        table = self.outbox
        statement = (
            select(table)
            .where(
                table.c.tenant_id == tenant_id,
                table.c.published_at.is_(None),
            )
            .order_by(table.c.created_at, table.c.id)
            .limit(batch)
            .with_for_update(skip_locked=True)
        )
        with self.engine.begin() as connection:
            set_tenant(connection, tenant_id)
            rows = connection.execute(statement).mappings().all()
            for row in rows:
                event = DocumentUploaded.model_validate(row["payload"])
                token = attach(extract({"traceparent": event.traceparent or ""}))
                try:
                    with stage("relay.publish"):
                        self.publisher.publish(
                            event.model_copy(
                                update={"traceparent": inject({}).get("traceparent")}
                            )
                        )
                finally:
                    detach(token)
                connection.execute(
                    table.update()
                    .where(
                        table.c.tenant_id == tenant_id,
                        table.c.id == row["id"],
                    )
                    .values(published_at=func.clock_timestamp())
                )
            return len(rows)

    def run(self, tenant_id: str, batch: int, poll: float, stop: Event) -> None:
        while not stop.is_set():
            for tenant in tenant_id.split(","):
                self.run_once(tenant, batch)
            stop.wait(poll)
