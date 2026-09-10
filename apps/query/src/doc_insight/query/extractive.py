"""Offline contiguous sentence windows from the highest-ranked passage."""

import re

from doc_insight.contracts.query import Generation
from doc_insight.query.ranking import overlap


class ExtractiveGenerator:
    def generate(self, question: str, passages: list[str]) -> Generation:
        if not passages:
            return Generation(answer="", supported=False)
        text = passages[0]
        boundaries = [0, *[m.end() for m in re.finditer(r"[.!?]\s+", text)], len(text)]
        windows = [
            text[start : boundaries[min(i + 2, len(boundaries) - 1)]].strip()
            for i, start in enumerate(boundaries[:-1])
        ]
        answer = max(windows, key=lambda window: overlap(question, window), default="")
        supported = bool(answer) and overlap(question, answer) >= 0.3
        return Generation(
            answer=answer,
            supported=supported,
            cited_passage_indexes=[0] if answer else [],
        )
