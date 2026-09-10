"""The command-line edge; document previews are explicit output, never log records."""

import argparse
import sys
from pathlib import Path

from doc_insight.contracts.structure import Document
from doc_insight.worker import store_cli, worker_cli
from doc_insight.worker.embedder import FastEmbedEmbedder
from doc_insight.worker.embedding import embed_document
from doc_insight.worker.extraction import extract
from doc_insight.worker.providers import (
    HfTokenizer,
    LinguaLanguageDetector,
    SpacyNerExtractor,
)
from doc_insight.worker.settings import get_settings
from doc_insight.worker.structure import analyze


def print_analysis(document: Document) -> None:
    print(f"Language: {document.language} | Pages: {document.page_count}")
    for page in document.pages:
        print(
            f"Page {page.number} | {page.language} | confidence={page.confidence:.3f}"
        )
    print("Entity | Label | Page | Count")
    for entity in document.entities:
        print(f"{entity.text} | {entity.label} | {entity.page} | {entity.count}")
    sizes = [chunk.token_count for chunk in document.chunks]
    print(
        f"Chunks: {len(sizes)} | Tokens min/max: {min(sizes, default=0)}/{max(sizes, default=0)}"
    )
    if document.embed_model:
        print(
            f"Embeddings: {document.embed_dimension} dimensions | {document.embed_model}"
        )


def analyze_file(path: Path, with_embeddings: bool) -> Document:
    settings = get_settings()
    document = analyze(
        extract(path),
        LinguaLanguageDetector(settings),
        SpacyNerExtractor(settings),
        HfTokenizer(settings),
        settings,
    )
    return (
        embed_document(document, FastEmbedEmbedder(settings))
        if with_embeddings
        else document
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="di")
    commands = parser.add_subparsers(dest="command", required=True)
    store_cli.add_commands(commands)
    worker_cli.add_commands(commands)
    for command, help_text in {
        "extract": "Extract text with OCR fallback",
        "analyze": "Detect language, entities and chunks",
    }.items():
        subcommand = commands.add_parser(command, help=help_text)
        subcommand.add_argument("path", type=Path)
        subcommand.add_argument("--json", action="store_true")
        if command == "analyze":
            subcommand.add_argument(
                "--embed", action="store_true", help="Generate chunk vectors"
            )
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "worker":
        worker_cli.run(parser)
        return
    if args.command in {"index", "show", "search"}:
        store_cli.run(args, parser)
        return
    if args.command == "analyze":
        structured = analyze_file(args.path, args.embed)
        if args.json:
            print(structured.model_dump_json(indent=2))
        else:
            print_analysis(structured)
        return
    document = extract(args.path)
    if args.json:
        print(document.model_dump_json(indent=2))
    else:
        print(f"Pages: {document.page_count} | {document.media_type}")
        for page in document.pages:
            print(f"Page {page.number} | {page.source} | {page.char_count} chars")
            print(page.text[:200])
