"""Regenerate the fixed retrieval questions; no model or network is involved."""

import json
from pathlib import Path

QUESTIONS = [
    ("Where does the observatory study Saturn through a telescope?", "quiet mountain"),
    ("What ingredients does the bakery use for sourdough?", "water and salt"),
    ("What happens when warm water causes coral bleaching?", "pale patches"),
    ("When do railway maintenance crews inspect the rails?", "at night"),
    ("Where does the hospital pharmacy store vaccines?", "monitored refrigerators"),
    ("How does the orchard water roots during dry weeks?", "drip irrigation"),
    ("What do wind turbines do in a severe storm?", "machines stop"),
    ("Why do tapestry conservators avoid strong light?", "dyes may fade"),
]


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "eval.jsonl"
    rows = [
        json.dumps({"question": question, "expected_substring": answer})
        for question, answer in QUESTIONS
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
