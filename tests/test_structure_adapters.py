import json
from pathlib import Path
from unittest.mock import patch

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
from doc_insight.worker.structure import analyze, chunk_page
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer as RustTokenizer

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
    assert result.language == "hr"
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
    settings = Settings(languages="de,en,hr", ner_models={"en": "test_english"})
    page = Page(
        number=1,
        text="Alice Johnson visited London.",
        source="text_layer",
        language="en",
    )
    load = providers.spacy.load
    with patch.object(
        providers.spacy,
        "load",
        side_effect=lambda name, **kw: load("en_core_web_sm", **kw),
    ) as spy:
        SpacyNerExtractor(settings).extract(page)
        SpacyNerExtractor(settings).extract(page)
        assert spy.call_count == 1
    with patch.object(
        providers.lingua,
        "LanguageDetectorBuilder",
        wraps=providers.lingua.LanguageDetectorBuilder,
    ) as builder:
        LinguaLanguageDetector(settings).detect(page.text)
        LinguaLanguageDetector(settings).detect(page.text)
        assert builder.from_iso_codes_639_1.call_count == 1


@pytest.mark.models
def test_hf_tokenizer_covers_a_long_page_and_caches_the_model(tmp_path: Path) -> None:
    settings = Settings(model_cache=tmp_path)
    tokenizer = HfTokenizer(settings)
    text = "Hello world. " * 1000
    with patch.object(providers, "hf_hub_download", wraps=hf_hub_download) as download:
        spans = tokenizer.encode(text)
        assert HfTokenizer(settings).encode(text) == spans
        assert download.call_count == 1
    assert len(spans) > 1000
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text.rstrip())
    assert list(settings.model_cache.rglob("tokenizer.json"))


@pytest.mark.models
@pytest.mark.parametrize("window,overlap", [(32, 8), (120, 24)])
@pytest.mark.parametrize(
    "filename",
    ["text_en.pdf", "text_hr.pdf", "text_long.pdf", "scanned.png", "mixed.pdf"],
)
def test_real_tokenizer_preserves_fixture_chunk_provenance(
    filename: str, window: int, overlap: int
) -> None:
    settings = Settings(chunk_tokens=window, chunk_overlap=overlap)
    tokenizer = HfTokenizer(settings)
    result = analyze(
        extract(FIXTURES / filename),
        FakeLanguageDetector(),
        FakeNerExtractor(),
        tokenizer,
        settings,
    )
    assert result.chunks
    for chunk in result.chunks:
        assert 0 < chunk.token_count <= window
        assert chunk.token_count == len(tokenizer.encode(chunk.text))
        text = result.pages[chunk.page - 1].text
        assert chunk.char_start == 0 or text[chunk.char_start - 1].isspace()
        assert chunk.char_end == len(text) or text[chunk.char_end].isspace()
        assert (
            result.pages[chunk.page - 1].text[chunk.char_start : chunk.char_end]
            == chunk.text
        )


@pytest.mark.models
def test_default_chunks_fit_the_pinned_sentence_model_with_special_tokens() -> None:
    settings = Settings()

    def download(filename: str) -> str:
        return hf_hub_download(
            settings.embed_model,
            filename,
            revision=settings.tokenizer_revision,
            cache_dir=settings.model_cache,
        )

    config = json.loads(
        Path(download("sentence_bert_config.json")).read_text(encoding="utf-8")
    )
    tokenizer = RustTokenizer.from_file(download("tokenizer.json"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    result = analyze(
        extract(FIXTURES / "text_long.pdf"),
        FakeLanguageDetector(),
        FakeNerExtractor(),
        HfTokenizer(settings),
        settings,
    )
    assert config["max_seq_length"] == 128
    assert (
        len(tokenizer.encode("hello").ids) - len(HfTokenizer(settings).encode("hello"))
        == 2
    )
    assert all(
        len(tokenizer.encode(chunk.text).ids) <= config["max_seq_length"]
        for chunk in result.chunks
    )


@pytest.mark.models
def test_a_long_url_is_cut_between_tokens_and_fully_covered() -> None:
    settings = Settings()
    tokenizer = HfTokenizer(settings)
    url = "https://example.com/reports/" + "a1b2c3d4e5f6" * 12 + ".pdf"
    page = Page(number=1, text=f"See {url} for details.", source="text_layer")
    assert len(tokenizer.encode(url)) > settings.chunk_tokens
    chunks = chunk_page(page, tokenizer, settings, 0)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert 0 < chunk.token_count <= settings.chunk_tokens
        assert chunk.token_count == len(tokenizer.encode(chunk.text))
        assert page.text[chunk.char_start : chunk.char_end] == chunk.text
    covered = {i for chunk in chunks for i in range(chunk.char_start, chunk.char_end)}
    assert all(i in covered for i, char in enumerate(page.text) if not char.isspace())
