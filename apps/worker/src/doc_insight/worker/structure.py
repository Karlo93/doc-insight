"""Ordered page analysis; adapters are supplied explicitly at the boundary."""

import re
from bisect import bisect_left, bisect_right
from itertools import pairwise
from unicodedata import category, normalize

from doc_insight.contracts.extraction import PIPELINE_VERSION, ExtractedDocument, Page
from doc_insight.contracts.structure import (
    Chunk,
    Document,
    Entity,
    LanguageDetector,
    NerExtractor,
    Tokenizer,
)
from doc_insight.worker._chunk_reference import _reference_chunk_page
from doc_insight.worker.settings import Settings


def _requires_reference(text: str) -> bool:
    # Normalization can erase separators before tokenization; retain raw-text cuts.
    return any(
        char not in "\t\n\r" and category(char) in {"Cc", "Cf", "Cs", "Co", "Zl", "Zp"}
        for char in text
    )


class _PageTokens:
    def __init__(self, text: str, tokenizer: Tokenizer) -> None:
        self.text, self.tokenizer = text, tokenizer
        offsets = tokenizer.encode(text)
        self.starts = [start for start, _ in offsets]
        self.ends = [end for _, end in offsets]
        self.ordered = all(a <= b for a, b in pairwise(self.starts)) and all(
            a <= b for a, b in pairwise(self.ends)
        )

    def count(self, start: int, end: int) -> int:
        # Cuts inside oversized words still need isolated tokenization.
        if (start > 0 and not self.text[start - 1].isspace()) or (
            end < len(self.text) and not self.text[end].isspace()
        ):
            return len(self.tokenizer.encode(self.text[start:end]))
        return bisect_right(self.ends, end) - bisect_left(self.starts, start)


def _units(page: Page, tokens: _PageTokens, cap: int) -> list[tuple[int, int]]:
    """Whole words, except that a word longer than the cap is cut between its tokens."""
    units: list[tuple[int, int]] = []
    for word in re.finditer(r"\S+", page.text):
        # Every token covers at least one character, so a short word always fits.
        if len(word.group()) <= cap or tokens.count(word.start(), word.end()) <= cap:
            units.append((word.start(), word.end()))
            continue
        units.extend(_split_word(word, tokens.tokenizer, cap))
    return units


def _split_word(
    word: re.Match[str], tokenizer: Tokenizer, cap: int
) -> list[tuple[int, int]]:
    offsets = tokenizer.encode(word.group())
    units: list[tuple[int, int]] = []
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


def _grow_window(
    units: list[tuple[int, int]], tokens: _PageTokens, first: int, cap: int
) -> tuple[int, int]:
    last, count = first, 0
    start = units[first][0]
    while last < len(units):
        size = tokens.count(start, units[last][1])
        if size > cap:
            break
        last, count = last + 1, size
    return last, count


def _overlap_start(
    units: list[tuple[int, int]],
    tokens: _PageTokens,
    first: int,
    last: int,
    budget: int,
) -> int:
    next_first = last
    end = units[last - 1][1]
    while next_first > first + 1:
        if tokens.count(units[next_first - 1][0], end) > budget:
            break
        next_first -= 1
    return next_first


def chunk_page(
    page: Page, tokenizer: Tokenizer, settings: Settings, start_ord: int
) -> list[Chunk]:
    """Overlap whole-word windows with half-open offsets and document-wide ordinals."""
    if _requires_reference(page.text):
        return _reference_chunk_page(page, tokenizer, settings, start_ord)
    tokens = _PageTokens(page.text, tokenizer)
    if not tokens.ordered:
        return _reference_chunk_page(page, tokenizer, settings, start_ord)
    units = _units(page, tokens, settings.chunk_tokens)
    chunks: list[Chunk] = []
    first = 0
    while first < len(units):
        last, count = _grow_window(units, tokens, first, settings.chunk_tokens)
        start = units[first][0]
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
        first = _overlap_start(units, tokens, first, last, settings.chunk_overlap)
    return chunks


def deduplicate(entities: list[Entity]) -> list[Entity]:
    """Group normalized spelling/label pairs, keeping first offsets and total count."""
    unique: dict[tuple[str, str], Entity] = {}
    for entity in sorted(entities, key=lambda item: (item.page, item.char_start)):
        key = (
            " ".join(normalize("NFKC", entity.text).casefold().split()),
            entity.label,
        )
        if key in unique:
            unique[key].count += entity.count
        else:
            unique[key] = entity.model_copy()
    return list(unique.values())


def analyze(
    document: ExtractedDocument,
    detector: LanguageDetector,
    ner: NerExtractor,
    tokenizer: Tokenizer,
    settings: Settings,
) -> Document:
    """Detect per-page language; cap document-wide NER while chunking every page."""
    pages: list[Page] = []
    chunks: list[Chunk] = []
    entities: list[Entity] = []
    remaining = settings.ner_max_chars
    for original in document.pages:
        guess = detector.detect(original.text[: settings.lang_sample_chars])
        language = (
            guess.language
            if guess.confidence >= settings.lang_min_confidence
            else "und"
        )
        page = original.model_copy(
            update={"language": language, "confidence": guess.confidence}
        )
        pages.append(page)
        text = page.text[:remaining]
        if text:
            entities.extend(ner.extract(page.model_copy(update={"text": text})))
        remaining -= len(text)
        chunks.extend(chunk_page(page, tokenizer, settings, len(chunks)))
    metadata = document.model_dump(exclude={"pages", "page_count", "pipeline_version"})
    return Document(
        **metadata,
        pipeline_version=PIPELINE_VERSION,
        pages=pages,
        chunks=chunks,
        entities=deduplicate(entities),
    )
