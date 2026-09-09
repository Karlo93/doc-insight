"""Ordered page analysis; adapters are supplied explicitly at the boundary."""

import re
from unicodedata import normalize

from doc_insight.contracts.extraction import PIPELINE_VERSION, ExtractedDocument, Page
from doc_insight.contracts.structure import (
    Chunk,
    Document,
    Entity,
    LanguageDetector,
    NerExtractor,
    Tokenizer,
)
from doc_insight.worker.settings import Settings


def chunk_page(
    page: Page, tokenizer: Tokenizer, settings: Settings, start_ord: int
) -> list[Chunk]:
    words = list(re.finditer(r"\S+", page.text))
    chunks: list[Chunk] = []
    first = 0
    while first < len(words):
        last, count = first, 0
        start = words[first].start()
        while last < len(words):
            size = len(tokenizer.encode(page.text[start : words[last].end()]))
            if size > settings.chunk_tokens:
                break
            last, count = last + 1, size
        if last == first:
            raise ValueError(f"A word on page {page.number} exceeds chunk_tokens")
        end = words[last - 1].end()
        if not chunks or end > chunks[-1].char_end:
            chunks.append(
                Chunk(
                    text=page.text[start:end],
                    page=page.number,
                    ord=start_ord + len(chunks),
                    char_start=start,
                    char_end=end,
                    token_count=count,
                )
            )
        if last == len(words):
            break
        next_first = last
        while next_first > first + 1:
            overlap = page.text[words[next_first - 1].start() : end]
            if len(tokenizer.encode(overlap)) > settings.chunk_overlap:
                break
            next_first -= 1
        first = next_first
    return chunks


def deduplicate(entities: list[Entity]) -> list[Entity]:
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
