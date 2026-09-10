from pathlib import Path
from unittest.mock import Mock

import pytest
from doc_insight.contracts.extraction import PIPELINE_VERSION, ExtractedDocument, Page
from doc_insight.contracts.structure import (
    Entity,
    LanguageDetector,
    LanguageGuess,
    NerExtractor,
)
from doc_insight.testing.structure import (
    FakeLanguageDetector,
    FakeNerExtractor,
    FakeTokenizer,
)
from doc_insight.worker.extraction import extract
from doc_insight.worker.settings import Settings
from doc_insight.worker.structure import analyze, deduplicate

FIXTURES = Path(__file__).parent / "fixtures"


def document(*texts: str) -> ExtractedDocument:
    return ExtractedDocument(
        sha256="a" * 64,
        media_type="application/pdf",
        pages=[
            Page(number=i, text=text, source="text_layer")
            for i, text in enumerate(texts, 1)
        ],
    )


def with_fakes(source: ExtractedDocument, **settings):
    return analyze(
        source,
        FakeLanguageDetector(),
        FakeNerExtractor(),
        FakeTokenizer(),
        Settings(**settings),
    )


@pytest.mark.parametrize(
    "filename",
    ["text_en.pdf", "text_hr.pdf", "text_long.pdf", "scanned.png", "mixed.pdf"],
)
def test_every_fixture_chunk_is_an_exact_page_slice(filename: str) -> None:
    # Offsets are citation boundaries: every emitted chunk must be an exact slice of its page.
    source = extract(FIXTURES / filename)
    result = with_fakes(source, chunk_tokens=32, chunk_overlap=8)
    assert result.chunks
    assert [chunk.ord for chunk in result.chunks] == list(range(len(result.chunks)))
    for chunk in result.chunks:
        page = result.pages[chunk.page - 1]
        assert page.text[chunk.char_start : chunk.char_end] == chunk.text
        assert 0 < chunk.token_count <= 32
        assert len(FakeTokenizer().encode(chunk.text)) == chunk.token_count
    assert source.pages[0].language == "und"
    assert result.pipeline_version == PIPELINE_VERSION


def test_overlapping_windows_cover_all_tokens_without_redundant_tail() -> None:
    words = [f"word{i}" for i in range(1000)]
    result = with_fakes(document(" ".join(words)))
    assert [chunk.token_count for chunk in result.chunks] == [120] * 10 + [40]
    for chunk, start in zip(result.chunks, range(0, 1000, 96), strict=True):
        assert chunk.text.split() == words[start : start + 120]
    for left, right in zip(result.chunks, result.chunks[1:]):
        assert left.text.split()[-24:] == right.text.split()[:24]


def test_page_boundaries_empty_pages_and_zero_overlap() -> None:
    result = with_fakes(
        document("one two", "", "three four"), chunk_tokens=1, chunk_overlap=0
    )
    assert [chunk.page for chunk in result.chunks] == [1, 1, 3, 3]
    assert [chunk.text for chunk in result.chunks] == ["one", "two", "three", "four"]
    assert with_fakes(document()).language == "und"
    assert with_fakes(document("   ")).chunks == []


@pytest.mark.parametrize(
    "languages,expected",
    [
        (["en", "en", "hr"], "en"),
        (["en", "hr"], "und"),
        (["en", "en", "hr", "de"], "und"),
        (["und", "und", "en"], "und"),
    ],
)
def test_document_language_requires_a_strict_majority(
    languages: list[str], expected: str
) -> None:
    detector = Mock(spec=LanguageDetector)
    detector.detect.side_effect = [
        LanguageGuess(language=code, confidence=1) for code in languages
    ]
    result = analyze(
        document(*["some text"] * len(languages)),
        detector,
        FakeNerExtractor(),
        FakeTokenizer(),
        Settings(),
    )
    assert result.language == expected
    assert result.model_dump()["language"] == expected


@pytest.mark.parametrize("confidence,expected", [(0.49, "und"), (0.5, "hr")])
def test_page_confidence_threshold(confidence: float, expected: str) -> None:
    result = analyze(
        document("Marko Marić živi u Zagrebu."),
        FakeLanguageDetector("hr", confidence),
        FakeNerExtractor(),
        FakeTokenizer(),
        Settings(),
    )
    assert result.pages[0].language == expected
    assert result.pages[0].confidence == confidence


def test_language_sample_and_cumulative_ner_budget() -> None:
    source = document("A" * 20, "B" * 20, "C" * 20)
    detector = Mock(spec=LanguageDetector)
    detector.detect.return_value = LanguageGuess(language="en", confidence=1)
    ner = Mock(spec=NerExtractor)
    ner.extract.return_value = []
    result = analyze(
        source,
        detector,
        ner,
        FakeTokenizer(),
        Settings(lang_sample_chars=5, ner_max_chars=30),
    )
    assert [call.args[0] for call in detector.detect.call_args_list] == [
        "A" * 5,
        "B" * 5,
        "C" * 5,
    ]
    assert [
        (call.args[0].number, len(call.args[0].text))
        for call in ner.extract.call_args_list
    ] == [(1, 20), (2, 10)]
    assert [page.char_count for page in result.pages] == [20, 20, 20]


def test_zero_ner_budget_never_calls_provider() -> None:
    ner = Mock(spec=NerExtractor)
    result = analyze(
        document("Alice Johnson"),
        FakeLanguageDetector(),
        ner,
        FakeTokenizer(),
        Settings(ner_max_chars=0),
    )
    ner.extract.assert_not_called()
    assert result.entities == []


def test_entity_dedup_preserves_first_position_and_does_not_mutate_input() -> None:
    first = Entity(text="Alice Johnson", label="PER", page=1, char_start=5, char_end=18)
    later = Entity(
        text="ALICE  JOHNSON", label="PER", page=2, char_start=0, char_end=14
    )
    other = first.model_copy(update={"label": "ORG"})
    result = deduplicate([later, first, other])
    assert len(result) == 2
    person = next(entity for entity in result if entity.label == "PER")
    assert person.count == 2
    assert (person.text, person.page, person.char_start, person.char_end) == (
        first.text,
        1,
        5,
        18,
    )
    assert first.count == later.count == 1


def test_entity_counts_across_pages() -> None:
    result = with_fakes(document("Alice Johnson in London", "Alice Johnson returned"))
    alice = next(entity for entity in result.entities if entity.text == "Alice Johnson")
    assert alice.count == 2
    assert alice.page == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_tokens": 0},
        {"chunk_tokens": 127},
        {"chunk_overlap": -1},
        {"chunk_tokens": 10, "chunk_overlap": 10},
        {"ner_max_chars": -1},
        {"lang_sample_chars": 0},
        {"lang_min_confidence": 1.1},
    ],
)
def test_invalid_settings_fail_early(overrides: dict) -> None:
    with pytest.raises(ValueError):
        Settings(**overrides)
