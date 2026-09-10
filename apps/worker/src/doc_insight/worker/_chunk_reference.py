"""Original candidate-retokenizing chunker for pages unsafe for offset counting."""

import re

from doc_insight.contracts.extraction import Page
from doc_insight.contracts.structure import Chunk, Tokenizer
from doc_insight.worker.settings import Settings


def _units(page: Page, tokenizer: Tokenizer, cap: int) -> list[tuple[int, int]]:
    """Whole words, except that a word longer than the cap is cut between its tokens."""
    units: list[tuple[int, int]] = []
    for word in re.finditer(r"\S+", page.text):
        # Every token covers at least one character, so a short word always fits.
        offsets = tokenizer.encode(word.group()) if len(word.group()) > cap else []
        if len(offsets) <= cap:
            units.append((word.start(), word.end()))
            continue
        # A long URL or OCR run has no whitespace to cut at. This is the only place a
        # chunk boundary may fall inside a word; failing the whole document was rejected.
        first = 0
        while first < len(offsets):
            last = first + 1
            while last < len(offsets):
                piece = word.group()[offsets[first][0] : offsets[last][1]]
                if len(tokenizer.encode(piece)) > cap:
                    break
                last += 1
            units.append(
                (word.start() + offsets[first][0], word.start() + offsets[last - 1][1])
            )
            first = last
    return units


def _reference_chunk_page(
    page: Page, tokenizer: Tokenizer, settings: Settings, start_ord: int
) -> list[Chunk]:
    units = _units(page, tokenizer, settings.chunk_tokens)
    chunks: list[Chunk] = []
    first = 0
    while first < len(units):
        last, count = first, 0
        start = units[first][0]
        while last < len(units):
            size = len(tokenizer.encode(page.text[start : units[last][1]]))
            if size > settings.chunk_tokens:
                break
            last, count = last + 1, size
        if last == first:
            raise ValueError(f"chunk_tokens too small on page {page.number}")
        end = units[last - 1][1]
        if not chunks or end > chunks[-1].char_end:
            chunks.append(
                Chunk(
                    text=page.text[start:end],
                    language=page.language,
                    page=page.number,
                    ord=start_ord + len(chunks),
                    char_start=start,
                    char_end=end,
                    token_count=count,
                )
            )
        if last == len(units):
            break
        next_first = last
        while next_first > first + 1:
            overlap = page.text[units[next_first - 1][0] : end]
            if len(tokenizer.encode(overlap)) > settings.chunk_overlap:
                break
            next_first -= 1
        first = next_first
    return chunks
