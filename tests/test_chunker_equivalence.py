"""Chunking equivalence against the implementation before page-level counting."""

import re
from pathlib import Path
from unittest.mock import Mock

import pytest
from doc_insight.contracts.extraction import Page
from doc_insight.contracts.structure import Chunk, Tokenizer
from doc_insight.testing.structure import FakeTokenizer
from doc_insight.worker import structure
from doc_insight.worker.extraction import extract
from doc_insight.worker.providers import HfTokenizer
from doc_insight.worker.settings import Settings
from doc_insight.worker.structure import chunk_page
from test_review_fixes import CharacterTokenizer, DoubledTokenizer


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


def reference_chunk_page(
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


WINDOWS = [(32, 8), (64, 8), (120, 24)]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.models
@pytest.mark.parametrize("window,overlap", WINDOWS)
@pytest.mark.parametrize(
    "filename",
    ["text_en.pdf", "text_hr.pdf", "text_long.pdf", "scanned.png", "mixed.pdf"],
)
def test_model_fixture_equivalence(filename: str, window: int, overlap: int) -> None:
    # Compare against the preserved algorithm before accepting a faster token-counting path.
    settings = Settings(chunk_tokens=window, chunk_overlap=overlap)
    tokenizer = HfTokenizer(settings)
    source = extract(FIXTURES / filename)
    ordinal = 7
    for page in source.pages:
        expected = reference_chunk_page(page, tokenizer, settings, ordinal)
        assert chunk_page(page, tokenizer, settings, ordinal) == expected
        ordinal += len(expected)


@pytest.mark.parametrize("tokenizer", [FakeTokenizer(), CharacterTokenizer()])
@pytest.mark.parametrize("prefix", ["", "\x0b"], ids=["fast", "reference"])
@pytest.mark.parametrize("window,overlap", WINDOWS + [(5, 0), (10, 4), (13, 4), (1, 0)])
@pytest.mark.parametrize(
    "text",
    [
        "",
        " \t\n ",
        "one two",
        "observatory weather cloud",
        "see confidential now",
        "a b c d abcdefghij",
        " \tČćđšž\nZagreb 😀.  weather\r\ncloud ",
        "before " + "abcdefghij" * 30 + " after",
        " ".join(f"word{i}" for i in range(121)),
        " ".join(f"word{i}" for i in range(1000)),
    ],
)
def test_fake_equivalence(
    tokenizer: Tokenizer, prefix: str, window: int, overlap: int, text: str
) -> None:
    settings = Settings(chunk_tokens=window, chunk_overlap=overlap)
    page = Page(number=3, text=prefix + text, source="text_layer", language="hr")
    expected = reference_chunk_page(page, tokenizer, settings, 9)
    assert chunk_page(page, tokenizer, settings, 9) == expected


@pytest.mark.parametrize("text", ["confidential", "\x0bconfidential"])
def test_degenerate_budget_equivalence(text: str) -> None:
    page = Page(number=2, text=text, source="text_layer")
    settings = Settings(chunk_tokens=1, chunk_overlap=0)
    for implementation in (reference_chunk_page, chunk_page):
        with pytest.raises(ValueError) as error:
            implementation(page, DoubledTokenizer(), settings, 0)
        assert str(error.value) == "chunk_tokens too small on page 2"


def test_normal_page_is_encoded_once() -> None:
    page = Page(
        number=1,
        text=" ".join(f"word{i}" for i in range(1000)) + " " + "z" * 500,
        source="text_layer",
    )
    tokenizer = Mock(wraps=FakeTokenizer())
    assert chunk_page(page, tokenizer, Settings(), 0)
    tokenizer.encode.assert_called_once_with(page.text)


@pytest.mark.models
@pytest.mark.parametrize("window,overlap", WINDOWS + [(5, 0)])
def test_model_oversized_word_equivalence(window: int, overlap: int) -> None:
    settings = Settings(chunk_tokens=window, chunk_overlap=overlap)
    tokenizer = HfTokenizer(settings)
    word = "https://example.org/astronomy?weather=cloud&" * 30
    assert len(tokenizer.encode(word)) > window
    page = Page(
        number=4, text=f"before {word} after", source="text_layer", language="en"
    )
    assert chunk_page(page, tokenizer, settings, 11) == reference_chunk_page(
        page, tokenizer, settings, 11
    )


@pytest.mark.models
def test_safe_word_boundary_counts_match_page_offsets() -> None:
    tokenizer = HfTokenizer(Settings())
    text = "  Čćđšž Zagreb 😀.\nHello,\tworld! café cafe\u0301\u00a0１２３\r\nhttps://example.org/a?b=c  "
    assert not structure._requires_reference(text)
    offsets = tokenizer.encode(text)
    words = list(re.finditer(r"\S+", text))
    for first, word in enumerate(words):
        for last in words[first:]:
            start, end = word.start(), last.end()
            expected = len(tokenizer.encode(text[start:end]))
            assert (
                sum(start <= left and right <= end for left, right in offsets)
                == expected
            )


GUARD_CASES = [
    pytest.param("a\x0b. b", True, id="vertical-tab"),
    pytest.param("a\u200b. b", True, id="zero-width-space"),
    pytest.param("a\u00ad. b", True, id="soft-hyphen"),
    pytest.param("a\u2028b c", True, id="line-separator"),
    pytest.param("a\u2029b c", True, id="paragraph-separator"),
    pytest.param("a\ue000b c", True, id="private-use"),
    pytest.param("a\x00b c", True, id="null-control"),
    pytest.param("a\u00a0b c", False, id="nbsp"),
    pytest.param("a b\tc\nd\re", False, id="plain-whitespace"),
    pytest.param("a\x0b. b\u200b c\u00ad d\u2028e\u00a0f", True, id="mixed"),
]


@pytest.mark.parametrize("text,guarded", GUARD_CASES + [("a\ud800b c", True)])
def test_guard_selects_page_path(
    monkeypatch: pytest.MonkeyPatch, text: str, guarded: bool
) -> None:
    reference = Mock(wraps=structure._reference_chunk_page)
    monkeypatch.setattr(structure, "_reference_chunk_page", reference)
    tokenizer = Mock(wraps=FakeTokenizer())
    page = Page(number=2, text=text, source="text_layer", language="hr")
    settings = Settings(chunk_tokens=2, chunk_overlap=1)
    expected = reference_chunk_page(page, FakeTokenizer(), settings, 7)
    assert chunk_page(page, tokenizer, settings, 7) == expected
    if guarded:
        reference.assert_called_once_with(page, tokenizer, settings, 7)
    else:
        reference.assert_not_called()
        tokenizer.encode.assert_called_once_with(text)


@pytest.mark.models
@pytest.mark.parametrize("text,guarded", GUARD_CASES)
@pytest.mark.parametrize("window,overlap", [(2, 1), (5, 0)] + WINDOWS)
def test_guarded_model_equivalence(
    text: str, guarded: bool, window: int, overlap: int
) -> None:
    settings = Settings(chunk_tokens=window, chunk_overlap=overlap)
    tokenizer = HfTokenizer(settings)
    page = Page(number=3, text=text, source="text_layer", language="en")
    assert structure._requires_reference(text) is guarded
    expected = reference_chunk_page(page, tokenizer, settings, 11)
    chunks = chunk_page(page, tokenizer, settings, 11)
    assert chunks == expected
    for chunk in chunks:
        assert len(tokenizer.encode(chunk.text)) == chunk.token_count <= window


@pytest.mark.parametrize("order", ["reversed", "nested"])
def test_non_monotonic_offsets_use_reference(
    monkeypatch: pytest.MonkeyPatch, order: str
) -> None:
    class UnorderedTokenizer:
        def encode(self, text: str) -> list[tuple[int, int]]:
            offsets = FakeTokenizer().encode(text)
            if order == "reversed":
                return offsets[::-1]
            # Starts remain ordered while ends move backwards within each word.
            return [
                span
                for start, end in offsets
                for span in [(start, end), (start, start + 1)]
            ]

    tokenizer = UnorderedTokenizer()
    reference = Mock(wraps=structure._reference_chunk_page)
    monkeypatch.setattr(structure, "_reference_chunk_page", reference)
    settings = Settings(chunk_tokens=4, chunk_overlap=1)
    page = Page(number=2, text="one two three four five", source="text_layer")
    expected = reference_chunk_page(page, tokenizer, settings, 7)
    chunks = chunk_page(page, tokenizer, settings, 7)
    assert chunks == expected
    reference.assert_called_once_with(page, tokenizer, settings, 7)
    assert all(
        len(tokenizer.encode(chunk.text)) == chunk.token_count <= 4 for chunk in chunks
    )
