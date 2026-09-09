"""The command-line edge; document previews are explicit output, never log records."""

import argparse
import sys
from pathlib import Path

from doc_insight.contracts.structure import Document
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="di")
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in {
        "extract": "Extract text with OCR fallback",
        "analyze": "Detect language, entities and chunks",
    }.items():
        subcommand = commands.add_parser(command, help=help_text)
        subcommand.add_argument("path", type=Path)
        subcommand.add_argument("--json", action="store_true")
    args = parser.parse_args()
    # Redirected Windows stdout may otherwise reject Croatian characters.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    document = extract(args.path)
    if args.command == "analyze":
        settings = get_settings()
        structured = analyze(
            document,
            LinguaLanguageDetector(settings),
            SpacyNerExtractor(settings),
            HfTokenizer(settings),
            settings,
        )
        if args.json:
            print(structured.model_dump_json(indent=2))
        else:
            print_analysis(structured)
        return
    if args.json:
        print(document.model_dump_json(indent=2))
    else:
        print(f"Pages: {document.page_count} | {document.media_type}")
        for page in document.pages:
            print(f"Page {page.number} | {page.source} | {page.char_count} chars")
            print(page.text[:200])
