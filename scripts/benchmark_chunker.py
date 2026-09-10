"""Compare the preserved reference and guarded chunker on local documents."""

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from statistics import median
from time import perf_counter

from doc_insight.contracts.extraction import Page
from doc_insight.contracts.structure import Chunk, Tokenizer
from doc_insight.worker._chunk_reference import _reference_chunk_page
from doc_insight.worker.extraction import extract
from doc_insight.worker.providers import HfTokenizer
from doc_insight.worker.settings import Settings
from doc_insight.worker.structure import _requires_reference, chunk_page

Chunker = Callable[[Page, Tokenizer, Settings, int], list[Chunk]]


def chunk_pages(
    pages: list[Page], tokenizer: Tokenizer, settings: Settings, implementation: Chunker
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in pages:
        chunks.extend(implementation(page, tokenizer, settings, len(chunks)))
    return chunks


def benchmark(path: Path, settings: Settings, tokenizer: Tokenizer) -> dict:
    samples: dict[str, list[float]] = {
        key: [] for key in ("extract", "encode", "reference", "guarded")
    }
    for repeat in range(3):
        started = perf_counter()
        document = extract(path)
        samples["extract"].append(perf_counter() - started)
        started = perf_counter()
        for page in document.pages:
            tokenizer.encode(page.text)
        samples["encode"].append(perf_counter() - started)
        outputs = {}
        implementations = [
            ("reference", _reference_chunk_page),
            ("guarded", chunk_page),
        ]
        # Alternate order to avoid consistently favoring one chunker after warmup.
        for name, implementation in implementations[:: -1 if repeat % 2 else 1]:
            started = perf_counter()
            outputs[name] = chunk_pages(
                document.pages, tokenizer, settings, implementation
            )
            samples[name].append(perf_counter() - started)
            print(
                f"pages={document.page_count} run={repeat + 1} {name}={samples[name][-1]:.6f}s",
                flush=True,
            )
        if outputs["reference"] != outputs["guarded"]:
            raise AssertionError("Reference and guarded chunks differ")
    return {
        "pages": document.page_count,
        "chunks": len(outputs["guarded"]),
        "guarded_pages": sum(_requires_reference(page.text) for page in document.pages),
        "ocr_pages": sum(page.source == "ocr" for page in document.pages),
        "equal": True,
        "seconds_median": {name: median(values) for name, values in samples.items()},
        "seconds_samples": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    settings = Settings(chunk_tokens=120, chunk_overlap=24)
    tokenizer = HfTokenizer(settings)
    tokenizer.encode("Warm the pinned tokenizer before timing.")
    for index, path in enumerate(args.paths, 1):
        result = benchmark(path, settings, tokenizer)
        print(json.dumps({"input": index, **result}), flush=True)


if __name__ == "__main__":
    main()
