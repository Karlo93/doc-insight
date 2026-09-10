"""RLS usage reservations and an index for existing full-text retrieval."""

from alembic import op

revision = "0004_usage_and_search"
down_revision = "0003_ingest_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE llm_budgets (
            tenant_id text NOT NULL, day date NOT NULL,
            charged bigint NOT NULL DEFAULT 0 CHECK (charged >= 0),
            reserved bigint NOT NULL DEFAULT 0 CHECK (reserved >= 0),
            PRIMARY KEY (tenant_id, day)
        )
    """)
    op.execute("""
        CREATE TABLE llm_usage (
            id uuid PRIMARY KEY, tenant_id text NOT NULL, day date NOT NULL,
            model text NOT NULL, reserved_tokens bigint NOT NULL CHECK (reserved_tokens > 0),
            input_tokens bigint NOT NULL DEFAULT 0, output_tokens bigint NOT NULL DEFAULT 0,
            cached_input_tokens bigint NOT NULL DEFAULT 0, request_id text,
            outcome text NOT NULL DEFAULT 'reserved',
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (tenant_id, day) REFERENCES llm_budgets(tenant_id, day)
        )
    """)
    for table in ("llm_budgets", "llm_usage"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY tenant_isolation ON {table} FOR ALL
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))""")
    op.execute("CREATE INDEX ix_llm_usage_tenant_day ON llm_usage (tenant_id, day)")
    op.execute(
        "CREATE INDEX ix_chunks_fulltext ON chunks USING gin (to_tsvector('simple'::regconfig, text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_chunks_fulltext")
    op.drop_table("llm_usage")
    op.drop_table("llm_budgets")
