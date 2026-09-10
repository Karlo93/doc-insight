import json
import runpy
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from doc_insight.contracts.embedding import Embedder
from doc_insight.contracts.structure import Chunk
from doc_insight.testing.embedding import KeywordEmbedder
from doc_insight.testing.structure import FakeTokenizer
from doc_insight.worker.embedder import FastEmbedEmbedder
from doc_insight.worker.evaluation import EvaluationCase, evaluate
from doc_insight.worker.extraction import extract
from doc_insight.worker.providers import HfTokenizer
from doc_insight.worker.settings import Settings
from doc_insight.worker.structure import chunk_page

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "provider", ["keyword", pytest.param("fastembed", marks=pytest.mark.models)]
)
@pytest.mark.parametrize("language", ["en", "hr"])
def test_retrieval_recall_on_fixed_questions(provider: str, language: str) -> None:
    # Frozen questions make recall changes attributable to retrieval rather than a moving test corpus.
    settings = Settings(chunk_tokens=64, chunk_overlap=8)
    tokenizer = HfTokenizer(settings) if provider == "fastembed" else FakeTokenizer()
    embedder = (
        FastEmbedEmbedder(settings) if provider == "fastembed" else KeywordEmbedder()
    )
    suffix = "_hr" if language == "hr" else ""
    cases = [
        EvaluationCase.model_validate_json(line)
        for line in (FIXTURES / f"eval{suffix}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    pages = extract(FIXTURES / f"text_long{suffix}.pdf").pages
    chunks = []
    for page in pages:
        chunks.extend(chunk_page(page, tokenizer, settings, len(chunks)))
    assert len(cases) == 8
    assert len(chunks) >= 24
    for case in cases:
        assert len(case.expected_substring.split()) <= 5
        assert any(case.expected_substring in page.text for page in pages)
    metrics = evaluate(cases, chunks, embedder)
    # Whitespace hashing cannot match inflected Croatian forms; measured baseline is 0.5.
    keyword_gate = 0.5 if language == "hr" else 0.75
    assert metrics.recall_at_5 >= (0.8 if provider == "fastembed" else keyword_gate)


@pytest.mark.parametrize("language", ["en", "hr"])
def test_answers_occur_exactly_once_in_source_pages(language: str) -> None:
    suffix = "_hr" if language == "hr" else ""
    pages = extract(FIXTURES / f"text_long{suffix}.pdf").pages
    rows = [
        json.loads(line)
        for line in (FIXTURES / f"eval{suffix}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(pages) == 6
    assert len(rows) == 8
    assert len({row["question"] for row in rows}) == 8
    for row in rows:
        answer = row["expected_substring"]
        assert 1 <= len(answer.split()) <= 5
        assert sum(page.text.count(answer) for page in pages) == 1, answer
        if language == "hr":
            assert row["question_en"].strip()
            assert row["question_en"] != row["question"]


def test_croatian_topics_round_trip_and_font_covers_diacritics() -> None:
    from fontTools.ttLib import TTFont

    scripts = FIXTURES.parents[1] / "scripts"
    paragraphs = runpy.run_path(str(scripts / "fixture_hr.py"))["PARAGRAPHS_HR"]
    pages = extract(FIXTURES / "text_long_hr.pdf").pages
    assert len(paragraphs) == 12
    for paragraph in paragraphs:
        assert 80 <= len(paragraph.split()) <= 120
        assert set(paragraph) & set("čćđšžČĆĐŠŽ")
    for index, page in enumerate(pages):
        expected = " ".join(paragraphs[2 * index : 2 * index + 2])
        assert " ".join(page.text.split()) == expected
    with TTFont(scripts / "fonts" / "fixture-sans.ttf") as font:
        assert set(map(ord, "čćđšž ČĆĐŠŽ")) <= font.getBestCmap().keys()


def test_cross_lingual_cases_use_translations_and_keep_croatian_answers() -> None:
    script = runpy.run_path(str(FIXTURES.parents[1] / "scripts" / "eval_retrieval.py"))
    original = script["load_cases"]("hr")
    translated = script["load_cases"]("hr", translated=True)
    rows = [
        json.loads(line)
        for line in (FIXTURES / "eval_hr.jsonl").read_text("utf-8").splitlines()
    ]
    assert [case.question for case in translated] == [
        row["question_en"] for row in rows
    ]
    assert [case.expected_substring for case in translated] == [
        case.expected_substring for case in original
    ]


@pytest.mark.parametrize(
    "args, directions, window",
    [
        ([], ["en->en"], "64/8"),
        (
            ["--language", "hr", "--provider", "all", "--production"],
            ["hr->hr", "hr->hr", "en->hr (report only)"],
            "120/24",
        ),
    ],
)
def test_evaluation_cli_selects_language_providers_and_window(
    args, directions, window, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "doc_insight.worker.embedder.FastEmbedEmbedder",
        lambda settings: KeywordEmbedder(),
    )
    monkeypatch.setattr(
        "doc_insight.worker.providers.HfTokenizer", lambda settings: FakeTokenizer()
    )
    script = FIXTURES.parents[1] / "scripts" / "eval_retrieval.py"
    monkeypatch.setattr(sys, "argv", [str(script), *args])
    runpy.run_path(str(script), run_name="__main__")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(directions)
    for line, direction in zip(lines, directions, strict=True):
        assert f"language={direction} |" in line
        assert f"window={window} |" in line
        assert "questions=8 | recall@5=" in line
        assert " | MRR=" in line


def test_metrics_use_first_relevant_rank_and_count_missing_answers() -> None:
    chunks = [
        Chunk(text=text, page=1, ord=i, char_start=0, char_end=len(text), token_count=1)
        for i, text in enumerate(
            ["first", "second", "third", "fourth", "fifth", "sixth"]
        )
    ]
    embedder = Mock(spec=Embedder)
    embedder.embed_passages.return_value = [[6 - i, i] for i in range(6)]
    embedder.embed_query.return_value = [1, 0]
    cases = [
        EvaluationCase(question="query", expected_substring=text)
        for text in ["second", "sixth", "absent"]
    ]
    result = evaluate(cases, chunks, embedder)
    assert result.recall_at_5 == pytest.approx(1 / 3)
    assert result.mrr == pytest.approx((1 / 2 + 1 / 6) / 3)


def test_empty_corpus_and_invalid_evaluation_inputs() -> None:
    case = EvaluationCase(question="anything", expected_substring="missing")
    result = evaluate([case], [], KeywordEmbedder())
    assert result.recall_at_5 == result.mrr == 0
    with pytest.raises(ValueError, match="question"):
        evaluate([], [], KeywordEmbedder())
    broken = Mock(spec=Embedder)
    broken.embed_passages.return_value = [[1]]
    with pytest.raises(ValueError, match="one vector"):
        evaluate([case], [], broken)
