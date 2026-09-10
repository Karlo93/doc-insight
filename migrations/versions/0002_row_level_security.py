"""Enforce tenant scope even for table owners without BYPASSRLS."""

from alembic import op

revision = "0002_row_level_security"
down_revision = "0001_core_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("documents", "chunks", "entities"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table} FOR ALL
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
        """)


def downgrade() -> None:
    for table in ("documents", "chunks", "entities"):
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
