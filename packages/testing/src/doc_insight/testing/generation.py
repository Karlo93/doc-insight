"""Deterministic generator for orchestration contract tests."""

from doc_insight.contracts.query import Generation


class FakeGenerator:
    def generate(self, question: str, passages: list[str]) -> Generation:
        return Generation(
            answer=passages[0] if passages else "",
            supported=bool(passages),
            cited_passage_indexes=[0] if passages else [],
        )
