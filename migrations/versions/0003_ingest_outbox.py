"""Upload metadata and atomic tenant-scoped event registration."""

from alembic import op

revision = "0003_ingest_outbox"
down_revision = "0002_row_level_security"
branch_labels = None
depends_on = None
DERIVED = ("page_count", "language", "pipeline_version", "embed_model", "processed_at")


def upgrade() -> None:
    op.execute("""
        ALTER TABLE documents ADD COLUMN size_bytes bigint CHECK (size_bytes >= 0),
        ADD COLUMN object_key text, ADD COLUMN error text,
        ADD CONSTRAINT documents_status CHECK
            (status IN ('uploaded', 'processing', 'processed', 'failed'))
    """)
    for column in DERIVED:
        op.execute(f"ALTER TABLE documents ALTER COLUMN {column} DROP NOT NULL")
    op.execute("""
        CREATE TABLE outbox (
            id uuid PRIMARY KEY, tenant_id text NOT NULL, aggregate_id uuid NOT NULL,
            type text NOT NULL, payload jsonb NOT NULL,
            created_at timestamptz NOT NULL, published_at timestamptz,
            FOREIGN KEY (aggregate_id, tenant_id)
                REFERENCES documents(id, tenant_id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE INDEX ix_outbox_pending ON outbox (tenant_id, created_at, id)
        WHERE published_at IS NULL
    """)
    op.execute("ALTER TABLE outbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE outbox FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON outbox FOR ALL
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
    """)


def downgrade() -> None:
    # Refuse to invent processed metadata or discard pending uploads on rollback.
    for column in DERIVED:
        op.execute(f"ALTER TABLE documents ALTER COLUMN {column} SET NOT NULL")
    op.drop_table("outbox")
    op.execute("""
        ALTER TABLE documents DROP CONSTRAINT documents_status,
        DROP COLUMN error, DROP COLUMN object_key, DROP COLUMN size_bytes
    """)
