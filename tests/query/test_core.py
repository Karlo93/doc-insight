from uuid import UUID

import pytest
from doc_insight.contracts.storage import SearchHit
from doc_insight.contracts.structure import Chunk
from doc_insight.query.extractive import ExtractiveGenerator
from doc_insight.query.ranking import (
    confidence,
    fuse,
    lexical_query,
    should_abstain,
    words,
)


def hit(ordinal, score=0.45):
    return SearchHit(
        document_id=UUID(int=1),
        score=score,
        chunk=Chunk(
            text="The bakery uses flour, water and salt.",
            page=1,
            ord=ordinal,
            char_start=0,
            char_end=37,
            token_count=8,
        ),
    )


def test_rrf_hand_rankings_and_ties():
    a, b, c = hit(0), hit(1), hit(2)
    result = fuse([[a, b], [b, a, c]])
    assert [h.chunk.ord for h in result] == [0, 1, 2]
    assert result[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert result[1].score == result[0].score
    assert result[2].score == pytest.approx(1 / 63)
    assert a.score == 0.45


def test_rrf_empty_one_sided_and_duplicates():
    assert fuse([[], []]) == []
    assert fuse([[hit(0)], []])[0].score == pytest.approx(1 / 61)
    assert fuse([[hit(0), hit(0)]])[0].score == pytest.approx(1 / 61)
    with pytest.raises(ValueError):
        fuse([], 0)


@pytest.mark.parametrize(
    "scores,supported,answer,evidence,expected",
    [
        ([0.03, 0.015], True, "water salt", ["water and salt"], 0.85),
        ([0.03, 0.03], True, "water salt", ["water and salt"], 0.7),
        ([0.03], True, "water salt", ["water and salt"], 0.7),
        ([0.03], True, "water chocolate", ["water and salt"], 0.35),
        ([0.03], False, "water salt", ["water and salt"], 0),
        ([], True, "water", ["water"], 0),
        ([0.03], True, "", ["water"], 0),
        ([0.03], True, "water", [], 0),
        ([0.03], True, "the", ["the"], 0),
    ],
)
def test_confidence_formula(scores, supported, answer, evidence, expected):
    assert confidence(scores, supported, answer, evidence) == pytest.approx(expected)


def test_abstain_threshold_boundary():
    assert not should_abstain(0.6, 0.6, True)
    assert should_abstain(0.59, 0.6, True)
    assert should_abstain(1, 0, False)
    assert should_abstain(0, 0, True)


def test_natural_language_lexical_terms_are_disjunctive_and_operators_are_inert():
    assert lexical_query("What does the worker do?") == '"worker"'
    assert (
        lexical_query("Explain decimal base operations please")
        == '"base" OR "decimal" OR "operations"'
    )
    assert lexical_query('"worker" OR --database') == '"database" OR "worker"'
    assert lexical_query("What is it?") == ""


def test_uppercase_acronyms_survive_stop_word_removal():
    assert words("What is CAN?") == {"can"}
    assert words("what can it do") == set()
    assert lexical_query("Explain the CAN bus") == '"bus" OR "can"'
    assert lexical_query("CAN OR AND gate") == '"can" OR "gate"'
    generation = ExtractiveGenerator().generate(
        "What is CAN?", ["CAN is a serial bus. It links controllers."]
    )
    assert generation.supported and generation.answer.startswith("CAN is a serial bus")


def test_extractive_selects_contiguous_window_and_rejects_irrelevant_question():
    passage = "Birds fly. A bakery uses flour. Sourdough contains water and salt."
    generator = ExtractiveGenerator()
    result = generator.generate("What does sourdough contain?", [passage])
    assert result.supported
    assert result.answer in passage
    assert "water and salt" in result.answer
    assert result.cited_passage_indexes == [0]
    assert not generator.generate(
        "Who invented quantum computing?", [passage]
    ).supported
    assert not generator.generate("bakery", []).supported
