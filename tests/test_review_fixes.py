import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from doc_insight.contracts.extraction import Page
from doc_insight.contracts.structure import Document
from doc_insight.testing.structure import FakeTokenizer
from doc_insight.worker.cli import main
from doc_insight.worker.providers import SpacyNerExtractor
from doc_insight.worker.settings import Settings
from doc_insight.worker.structure import chunk_page


class CharacterTokenizer:
    def encode(self, text: str) -> list[tuple[int, int]]:
        return [(match.start(), match.end()) for match in re.finditer(r"\S", text)]


def test_subword_windows_keep_whole_words_and_exact_counts() -> None:
    # Token counts must describe the emitted text, including words split into several subwords.
    page = Page(number=1, text="observatory weather cloud", source="text_layer")
    chunks = chunk_page(
        page, CharacterTokenizer(), Settings(chunk_tokens=13, chunk_overlap=4), 0
    )
    assert [chunk.text for chunk in chunks] == ["observatory", "weather cloud"]
    assert [chunk.token_count for chunk in chunks] == [11, 12]
    assert all(
        page.text[chunk.char_start : chunk.char_end] == chunk.text for chunk in chunks
    )


class DoubledTokenizer:
    """Two tokens per character: a budget of one can never hold a token."""

    def encode(self, text: str) -> list[tuple[int, int]]:
        return [
            span
            for match in re.finditer(r"\S", text)
            for span in [(match.start(), match.end())] * 2
        ]


def test_one_oversized_word_is_cut_between_tokens_instead_of_failing() -> None:
    page = Page(number=2, text="see confidential now", source="text_layer")
    chunks = chunk_page(
        page, CharacterTokenizer(), Settings(chunk_tokens=5, chunk_overlap=0), 0
    )
    assert [chunk.text for chunk in chunks] == ["see", "confi", "denti", "al now"]
    assert [chunk.token_count for chunk in chunks] == [3, 5, 5, 5]
    assert all(
        page.text[chunk.char_start : chunk.char_end] == chunk.text for chunk in chunks
    )


def test_a_budget_too_small_for_one_token_fails_without_leaking_text() -> None:
    page = Page(number=2, text="confidential", source="text_layer")
    with pytest.raises(ValueError, match="page 2") as error:
        chunk_page(
            page, DoubledTokenizer(), Settings(chunk_tokens=1, chunk_overlap=0), 0
        )
    assert page.text not in str(error.value)


def test_a_large_next_word_does_not_emit_overlap_only_chunks() -> None:
    page = Page(number=1, text="a b c d abcdefghij", source="text_layer")
    chunks = chunk_page(
        page, CharacterTokenizer(), Settings(chunk_tokens=10, chunk_overlap=4), 0
    )
    assert [chunk.text for chunk in chunks] == ["a b c d", "abcdefghij"]
    assert [chunk.ord for chunk in chunks] == [0, 1]


def test_tiny_tail_keeps_all_words_without_exceeding_the_budget() -> None:
    page = Page(
        number=1, text=" ".join(f"word{i}" for i in range(121)), source="text_layer"
    )
    chunks = chunk_page(page, FakeTokenizer(), Settings(), 0)
    assert [chunk.token_count for chunk in chunks] == [120, 25]
    assert chunks[-1].text.endswith("word120")


@pytest.mark.parametrize(
    "pages,expected",
    [
        ([("English content", "en"), ("", "und")], "en"),
        ([("a" * 100, "hr"), ("short", "en"), ("short", "en")], "hr"),
        ([("equal", "en"), ("equal", "hr")], "und"),
        ([("a" * 100, "und"), ("short", "en")], "und"),
        ([("", "und")], "und"),
    ],
)
def test_document_language_weights_characters(
    pages: list[tuple[str, str]], expected: str
) -> None:
    document = Document(
        sha256="a" * 64,
        media_type="application/pdf",
        chunks=[],
        entities=[],
        pages=[
            Page(number=i, text=text, language=code, source="text_layer")
            for i, (text, code) in enumerate(pages, 1)
        ],
    )
    assert document.language == expected


def test_ner_discards_newline_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = [
        SimpleNamespace(text=text, label_="PERSON", start_char=start, end_char=end)
        for text, start, end in [("Salary Guidance\nLIFE", 0, 20), ("Alice", 21, 26)]
    ]
    monkeypatch.setattr(
        "doc_insight.worker.providers.spacy.load",
        Mock(return_value=lambda text: SimpleNamespace(ents=spans)),
    )
    settings = Settings(ner_models={"en": "test_layout"})
    page = Page(
        number=1, text="Salary Guidance\nLIFE Alice", source="text_layer", language="en"
    )
    assert [entity.text for entity in SpacyNerExtractor(settings).extract(page)] == [
        "Alice"
    ]


def test_default_cache_is_independent_of_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DI_MODEL_CACHE", raising=False)
    before = Settings().model_cache
    monkeypatch.chdir(tmp_path)
    assert Settings().model_cache == before
    assert before.is_absolute()


def test_help_describes_both_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["di", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "Extract text with OCR fallback" in output
    assert "Detect language, entities and chunks" in output
