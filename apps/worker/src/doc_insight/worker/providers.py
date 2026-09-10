"""Model I/O is lazy and cached by configuration, never by document."""

import logging
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import lingua
import spacy
from doc_insight.contracts.extraction import Page
from doc_insight.contracts.settings import EmbeddingSettings
from doc_insight.contracts.structure import Entity, LanguageGuess
from doc_insight.worker.settings import Settings
from huggingface_hub import hf_hub_download
from spacy.language import Language
from tokenizers import Tokenizer as RustTokenizer

logger = logging.getLogger(__name__)


@cache
def _language_model(codes: str) -> lingua.LanguageDetector:
    languages = [
        lingua.IsoCode639_1.from_str(code.strip()) for code in codes.split(",")
    ]
    return lingua.LanguageDetectorBuilder.from_iso_codes_639_1(*languages).build()


@cache
def _ner_model(name: str) -> Language:
    return spacy.load(
        name, exclude=["tagger", "parser", "attribute_ruler", "lemmatizer"]
    )


@cache
def _tokenizer(model: str, revision: str, cache_dir: Path) -> RustTokenizer:
    path = hf_hub_download(
        model, "tokenizer.json", revision=revision, cache_dir=cache_dir
    )
    tokenizer = RustTokenizer.from_file(path)
    # Page offsets must cover the entire input, without padding or special tokens.
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


@dataclass
class LinguaLanguageDetector:
    settings: Settings

    def detect(self, text: str) -> LanguageGuess:
        values = _language_model(
            self.settings.languages
        ).compute_language_confidence_values(text)
        if not values or values[0].value == 0:
            return LanguageGuess(language="und", confidence=0)
        best = values[0]
        return LanguageGuess(
            language=best.language.iso_code_639_1.name.lower(), confidence=best.value
        )


@dataclass
class SpacyNerExtractor:
    settings: Settings

    def extract(self, page: Page) -> list[Entity]:
        model = self.settings.ner_models.get(page.language)
        if model is None:
            logger.info(
                "NER skipped: no model for language=%s page=%d",
                page.language,
                page.number,
            )
            return []
        return [
            Entity(
                text=span.text,
                label=span.label_,
                page=page.number,
                char_start=span.start_char,
                char_end=span.end_char,
            )
            for span in _ner_model(model)(page.text).ents
            if "\n" not in span.text
        ]


@dataclass
class HfTokenizer:
    settings: EmbeddingSettings

    def encode(self, text: str) -> list[tuple[int, int]]:
        tokenizer = _tokenizer(
            self.settings.embed_model,
            self.settings.tokenizer_revision,
            self.settings.model_cache,
        )
        return [
            (start, end)
            for start, end in tokenizer.encode(text, add_special_tokens=False).offsets
            if start < end
        ]
