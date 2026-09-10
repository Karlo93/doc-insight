"""SQL operations shared by ingestion and processing repositories."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from doc_insight.contracts.ingest import DocumentStatus, DocumentUploaded
from doc_insight.contracts.storage import StoredDocument
from doc_insight.observability import inject
from sqlalchemy import Connection, Engine, Table, select, text
from sqlalchemy.dialects.postgresql import insert


def set_tenant(connection: Connection, tenant_id: str) -> None:
    """Bind RLS context to this transaction so pooled connections cannot retain it."""
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant_id}
    )


class UploadRepository:
    engine: Engine
    docs: Table
    outbox: Table

    def list_documents(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[StoredDocument]:
        """Return metadata only, in stable newest-first order under tenant RLS."""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        with self.engine.begin() as connection:
            set_tenant(connection, tenant_id)
            rows = connection.execute(
                select(self.docs)
                .where(self.docs.c.tenant_id == tenant_id)
                .order_by(self.docs.c.created_at.desc(), self.docs.c.id)
                .limit(limit)
                .offset(offset)
            ).mappings()
            return [StoredDocument.model_validate(row) for row in rows]

    def find_by_sha256(self, tenant_id: str, sha256: str) -> StoredDocument | None:
        """Look up a duplicate only within the requesting tenant."""
        with self.engine.begin() as connection:
            set_tenant(connection, tenant_id)
            row = (
                connection.execute(
                    select(self.docs).filter_by(tenant_id=tenant_id, sha256=sha256)
                )
                .mappings()
                .one_or_none()
            )
            return StoredDocument.model_validate(row) if row else None

    def register_upload(
        self,
        tenant_id: str,
        filename: str,
        sha256: str,
        media_type: str,
        size_bytes: int,
        object_key: str,
    ) -> StoredDocument:
        """Register uploaded metadata and an outbox event, or return the existing record."""
        record = StoredDocument(
            id=uuid4(),
            tenant_id=tenant_id,
            filename=filename,
            sha256=sha256,
            media_type=media_type,
            size_bytes=size_bytes,
            object_key=object_key,
            status="uploaded",
            created_at=datetime.now(UTC),
        )
        return self._register(record)

    def _register(self, record: StoredDocument) -> StoredDocument:
        """Let the tenant/hash constraint choose one winner and enqueue only that insert."""
        statement = (
            insert(self.docs)
            .values(**record.model_dump(exclude={"chunks", "entities"}))
            .on_conflict_do_nothing(index_elements=["tenant_id", "sha256"])
            .returning(self.docs)
        )
        with self.engine.begin() as connection:
            set_tenant(connection, record.tenant_id)
            row = connection.execute(statement).mappings().one_or_none()
            if row is None:
                # Another upload won the unique key; return its ID without a second event.
                row = (
                    connection.execute(
                        select(self.docs).filter_by(
                            tenant_id=record.tenant_id, sha256=record.sha256
                        )
                    )
                    .mappings()
                    .one()
                )
            else:
                self._enqueue(connection, record)
            return StoredDocument.model_validate(row)

    def _enqueue(self, connection: Connection, record: StoredDocument) -> None:
        """Persist the event and active trace parent in the document transaction."""
        event = DocumentUploaded(
            tenant_id=record.tenant_id,
            document_id=record.id,
            sha256=record.sha256,
            media_type=record.media_type,
            size_bytes=record.size_bytes or 0,
            object_key=record.object_key or "",
            occurred_at=record.created_at,
            traceparent=inject({}).get("traceparent"),
        )
        connection.execute(
            self.outbox.insert().values(
                id=event.event_id,
                tenant_id=record.tenant_id,
                aggregate_id=record.id,
                type=event.type,
                payload=event.model_dump(mode="json", exclude_none=True),
                created_at=event.occurred_at,
            )
        )

    def mark_status(
        self,
        tenant_id: str,
        document_id: UUID,
        status: DocumentStatus,
        error: str | None = None,
    ) -> None:
        """Update tenant-owned status; retain a sanitized error only for failures."""
        # Callers supply a sanitized error class/summary, never exception text.
        if status not in {"uploaded", "processing", "processed", "failed"}:
            raise ValueError("Invalid document status")
        with self.engine.begin() as connection:
            set_tenant(connection, tenant_id)
            found = connection.execute(
                self.docs.update()
                .where(
                    self.docs.c.tenant_id == tenant_id,
                    self.docs.c.id == document_id,
                )
                .values(status=status, error=error if status == "failed" else None)
                .returning(self.docs.c.id)
            ).scalar_one_or_none()
            if found is None:
                raise LookupError("Document not found for tenant")
