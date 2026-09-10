"""The fixed MiniLM profile stores 384-dimensional vectors."""

from alembic import op

revision = "0001_core_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE documents (
            id uuid PRIMARY KEY, tenant_id text NOT NULL,
            sha256 text NOT NULL, filename text NOT NULL, media_type text NOT NULL,
            page_count integer NOT NULL, language text NOT NULL, status text NOT NULL,
            pipeline_version text NOT NULL, embed_model text NOT NULL,
            created_at timestamptz NOT NULL, processed_at timestamptz NOT NULL,
            UNIQUE (tenant_id, sha256), UNIQUE (id, tenant_id)
        )
    """)
    op.execute("""
        CREATE TABLE chunks (
            id uuid PRIMARY KEY, document_id uuid NOT NULL, tenant_id text NOT NULL,
            page integer NOT NULL, ord integer NOT NULL, text text NOT NULL,
            language text NOT NULL, char_start integer NOT NULL, char_end integer NOT NULL,
            token_count integer NOT NULL, embedding vector(384) NOT NULL,
            FOREIGN KEY (document_id, tenant_id) REFERENCES documents(id, tenant_id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE entities (
            id uuid PRIMARY KEY, document_id uuid NOT NULL, tenant_id text NOT NULL,
            text text NOT NULL, label text NOT NULL, page integer NOT NULL,
            char_start integer NOT NULL, char_end integer NOT NULL, count integer NOT NULL,
            FOREIGN KEY (document_id, tenant_id) REFERENCES documents(id, tenant_id) ON DELETE CASCADE
        )
    """)
    for table in ("documents", "chunks", "entities"):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.execute(
        "CREATE INDEX ix_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    for table in ("entities", "chunks", "documents"):
        op.drop_table(table)
    # Extensions may be shared by other applications in this database.
