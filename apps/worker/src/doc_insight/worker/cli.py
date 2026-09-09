"""The command-line edge; document previews are explicit output, never log records."""

import argparse
import sys
from pathlib import Path

from doc_insight.worker.extraction import extract


def main() -> None:
    parser = argparse.ArgumentParser(prog="di")
    commands = parser.add_subparsers(dest="command", required=True)
    extraction = commands.add_parser("extract", help="extract PDF/image text with OCR")
    extraction.add_argument("path", type=Path)
    extraction.add_argument("--json", action="store_true")
    args = parser.parse_args()
    # Redirected Windows stdout may otherwise reject Croatian characters.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    document = extract(args.path)
    if args.json:
        print(document.model_dump_json(indent=2))
    else:
        print(f"Pages: {document.page_count} | {document.media_type}")
        for page in document.pages:
            print(f"Page {page.number} | {page.source} | {page.char_count} chars")
            print(page.text[:200])
