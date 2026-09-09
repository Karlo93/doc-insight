import pytest
from doc_insight.contracts.extraction import Page
from doc_insight.contracts.structure import LanguageDetector, NerExtractor, Tokenizer
from doc_insight.testing.structure import (
    FakeLanguageDetector,
    FakeNerExtractor,
    FakeTokenizer,
)
from doc_insight.worker.providers import (
    HfTokenizer,
    LinguaLanguageDetector,
    SpacyNerExtractor,
)
from doc_insight.worker.settings import Settings


@pytest.fixture(params=["fake", "lingua"])
def detector(request: pytest.FixtureRequest) -> LanguageDetector:
    return (
        FakeLanguageDetector()
        if request.param == "fake"
        else LinguaLanguageDetector(Settings())
    )


@pytest.mark.parametrize(
    "text", ["", "Alice Johnson visited the British Museum in London."]
)
def test_language_contract(detector: LanguageDetector, text: str) -> None:
    guess = detector.detect(text)
    assert 0 <= guess.confidence <= 1
    assert guess.language == ("en" if text else "und")
    repeated = detector.detect(text)
    assert repeated.language == guess.language
    assert repeated.confidence == pytest.approx(guess.confidence)
    if not text:
        assert guess.confidence == 0


@pytest.fixture(params=["fake", "spacy"])
def ner(request: pytest.FixtureRequest) -> NerExtractor:
    return (
        FakeNerExtractor() if request.param == "fake" else SpacyNerExtractor(Settings())
    )


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", "Alice Johnson visited London."),
        ("hr", "Marko Marić živi u Zagrebu."),
    ],
)
def test_ner_contract(ner: NerExtractor, language: str, text: str) -> None:
    page = Page(number=3, text=text, source="text_layer", language=language)
    entities = ner.extract(page)
    assert entities
    for entity in entities:
        assert entity.page == 3
        assert 0 <= entity.char_start < entity.char_end <= len(text)
        assert text[entity.char_start : entity.char_end] == entity.text
        assert entity.label
        assert entity.count == 1
    assert ner.extract(page) == entities


def test_ner_contract_empty_and_unsupported(ner: NerExtractor) -> None:
    assert (
        ner.extract(Page(number=1, text="", source="text_layer", language="en")) == []
    )
    assert (
        ner.extract(
            Page(
                number=1,
                text="Alice Johnson in London",
                source="text_layer",
                language="de",
            )
        )
        == []
    )


@pytest.fixture(params=["fake", pytest.param("hf", marks=pytest.mark.models)])
def tokenizer(request: pytest.FixtureRequest) -> Tokenizer:
    return FakeTokenizer() if request.param == "fake" else HfTokenizer(Settings())


@pytest.mark.parametrize("text", ["", "Hello world.", "  Čćđšž Zagreb 😀. "])
def test_tokenizer_contract(tokenizer: Tokenizer, text: str) -> None:
    spans = tokenizer.encode(text)
    assert tokenizer.encode(text) == spans
    assert spans == sorted(spans)
    assert all(0 <= start < end <= len(text) for start, end in spans)
    if text.strip():
        assert spans
        assert spans[-1][1] == len(text.rstrip())
    else:
        assert spans == []
