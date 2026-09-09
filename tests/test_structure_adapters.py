from pathlib import Path

import pytest
from doc_insight.contracts.extraction import Page
from doc_insight.testing.structure import (
    FakeLanguageDetector,
    FakeNerExtractor,
    FakeTokenizer,
)
from doc_insight.worker import providers
from doc_insight.worker.extraction import extract
from doc_insight.worker.providers import (
    HfTokenizer,
    LinguaLanguageDetector,
    SpacyNerExtractor,
)
from doc_insight.worker.settings import Settings
from doc_insight.worker.structure import analyze

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "filename,language", [("text_en.pdf", "en"), ("text_hr.pdf", "hr")]
)
def test_real_language_and_ner_on_fixtures(filename: str, language: str) -> None:
    settings = Settings()
    result = analyze(
        extract(FIXTURES / filename),
        LinguaLanguageDetector(settings),
        SpacyNerExtractor(settings),
        FakeTokenizer(),
        settings,
    )
    assert result.language == language
    assert all(page.language == language for page in result.pages)
    assert result.entities
    if language == "hr":
        assert any(entity.label in {"PER", "LOC"} for entity in result.entities)


def test_real_language_detection_is_per_page() -> None:
    source = extract(FIXTURES / "text_en.pdf")
    croatian = (
        extract(FIXTURES / "text_hr.pdf").pages[0].model_copy(update={"number": 2})
    )
    source.pages.append(croatian)
    settings = Settings()
    result = analyze(
        source,
        LinguaLanguageDetector(settings),
        SpacyNerExtractor(settings),
        FakeTokenizer(),
        settings,
    )
    assert [page.language for page in result.pages] == ["en", "hr"]
    assert result.language == "und"
    assert {entity.page for entity in result.entities} == {1, 2}


def test_unsupported_ner_logs_metadata_only(caplog: pytest.LogCaptureFixture) -> None:
    text = "private content that must not appear in logs"
    with caplog.at_level("INFO", logger=providers.__name__):
        assert (
            SpacyNerExtractor(Settings()).extract(
                Page(number=4, text=text, source="text_layer", language="de")
            )
            == []
        )
    assert "language=de page=4" in caplog.text
    assert text not in caplog.text


def test_installed_models_load_once() -> None:
    assert providers._language_model("en,hr,de") is providers._language_model(
        "en,hr,de"
    )
    assert providers._ner_model("en_core_web_sm") is providers._ner_model(
        "en_core_web_sm"
    )
    assert providers._ner_model("hr_core_news_sm") is providers._ner_model(
        "hr_core_news_sm"
    )


@pytest.mark.models
def test_hf_tokenizer_covers_a_long_page_and_caches_the_model() -> None:
    settings = Settings()
    tokenizer = HfTokenizer(settings)
    text = "Hello world. " * 1000
    spans = tokenizer.encode(text)
    assert len(spans) > 1000
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text.rstrip())
    args = (settings.embed_model, settings.tokenizer_revision, settings.model_cache)
    assert providers._tokenizer(*args) is providers._tokenizer(*args)
    assert list(settings.model_cache.rglob("tokenizer.json"))


@pytest.mark.models
@pytest.mark.parametrize(
    "filename",
    ["text_en.pdf", "text_hr.pdf", "text_long.pdf", "scanned.png", "mixed.pdf"],
)
def test_real_tokenizer_preserves_fixture_chunk_provenance(filename: str) -> None:
    settings = Settings(chunk_tokens=32, chunk_overlap=8)
    result = analyze(
        extract(FIXTURES / filename),
        FakeLanguageDetector(),
        FakeNerExtractor(),
        HfTokenizer(settings),
        settings,
    )
    assert result.chunks
    for chunk in result.chunks:
        assert 0 < chunk.token_count <= 32
        assert (
            result.pages[chunk.page - 1].text[chunk.char_start : chunk.char_end]
            == chunk.text
        )
