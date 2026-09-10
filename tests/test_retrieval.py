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
def test_retrieval_recall_on_fixed_questions(provider: str) -> None:
    settings = Settings(chunk_tokens=64, chunk_overlap=8)
    tokenizer = HfTokenizer(settings) if provider == "fastembed" else FakeTokenizer()
    embedder = (
        FastEmbedEmbedder(settings) if provider == "fastembed" else KeywordEmbedder()
    )
    cases = [
        EvaluationCase.model_validate_json(line)
        for line in (FIXTURES / "eval.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    pages = extract(FIXTURES / "text_long.pdf").pages
    chunks = []
    for page in pages:
        chunks.extend(chunk_page(page, tokenizer, settings, len(chunks)))
    assert len(cases) == 8
    assert len(chunks) >= 25
    for case in cases:
        assert len(case.expected_substring.split()) <= 5
        assert any(case.expected_substring in page.text for page in pages)
    metrics = evaluate(cases, chunks, embedder)
    assert metrics.recall_at_5 >= (0.8 if provider == "fastembed" else 0.75)


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
