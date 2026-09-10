"""CLI orchestration keeps expensive processing outside the database transaction."""

import argparse
from pathlib import Path
from time import perf_counter
from uuid import UUID

from doc_insight.contracts.storage import DocumentRepository, StoredDocument
from doc_insight.worker.embedder import FastEmbedEmbedder
from doc_insight.worker.embedding import embed_document
from doc_insight.worker.extraction import extract
from doc_insight.worker.providers import (
    HfTokenizer,
    LinguaLanguageDetector,
    SpacyNerExtractor,
)
from doc_insight.worker.repository import PostgresRepository
from doc_insight.worker.settings import get_settings
from doc_insight.worker.structure import analyze
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError


def add_commands(
    commands: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    for name, kind, help_text in (
        ("index", Path, "Process and store a document"),
        ("show", UUID, "Show a stored document and citations"),
        ("search", str, "Find the nearest tenant-owned passages"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("value", type=kind)
        command.add_argument("--tenant", required=True)
        if name == "search":
            command.add_argument("-k", type=int, default=5)


def index_file(
    path: Path, tenant: str, repository: DocumentRepository
) -> StoredDocument:
    settings = get_settings()
    started = perf_counter()
    extracted = extract(path)
    extracted_at = perf_counter()
    document = analyze(
        extracted,
        LinguaLanguageDetector(settings),
        SpacyNerExtractor(settings),
        HfTokenizer(settings),
        settings,
    )
    analyzed_at = perf_counter()
    embedded = embed_document(document, FastEmbedEmbedder(settings))
    embedded_at = perf_counter()
    stored = repository.upsert_document(tenant, path.name, embedded)
    stored_at = perf_counter()
    print(
        f"extract={extracted_at - started:.3f}s analyze={analyzed_at - extracted_at:.3f}s embed={embedded_at - analyzed_at:.3f}s store={stored_at - embedded_at:.3f}s"
    )
    return stored


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not args.tenant.strip():
        parser.error("tenant must be nonblank")
    if args.command == "search" and args.k < 1:
        parser.error("k must be positive")
    if args.command == "search" and not args.value.strip():
        parser.error("search text must be nonblank")
    engine: Engine | None = None
    try:
        # A malformed URL fails here and must get the same sanitized message.
        engine = create_engine(get_settings().database_url, hide_parameters=True)
        repository = PostgresRepository(engine)
        if args.command == "search":
            vector = FastEmbedEmbedder(get_settings()).embed_query(args.value)
            for hit in repository.nearest_chunks(args.tenant, vector, args.k):
                print(
                    f"{hit.document_id} | Page {hit.chunk.page} | cosine={hit.score:.3f}\n{hit.chunk.text}"
                )
        elif args.command == "index":
            stored = index_file(args.value, args.tenant, repository)
            print(
                f"Document: {stored.id} | Chunks: {len(stored.chunks)} | Tenant: {stored.tenant_id}"
            )
        else:
            found = repository.get_document(args.tenant, args.value)
            if found is None:
                parser.error("Document not found for tenant")
            print(found.model_dump_json(indent=2))
    except SQLAlchemyError:
        parser.error("Database operation failed; check configuration and migrations")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    finally:
        if engine is not None:
            engine.dispose()
