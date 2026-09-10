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

QUESTIONS_HR = [
    (
        "Čime radnici skupljaju kristale u paškim bazenima?",
        "What tool do workers use to collect crystals in the Pag salt pans?",
        "drvene grablje",
    ),
    (
        "Zašto se voda nakon pljuska ne zadržava iza suhozida?",
        "Why does water not collect behind a dry stone wall after a downpour?",
        "kišnica prolazi",
    ),
    (
        "Po kakvom svjetlosnom signalu pomorac prepoznaje opisani svjetionik?",
        "What light signal lets a sailor recognize the lighthouse described?",
        "tri kratka bljeska",
    ),
    (
        "Kakvu poslasticu dobije pas kad nanjuši tartuf?",
        "What treat does the dog receive when it sniffs out a truffle?",
        "komadićem sira",
    ),
    (
        "Pomoću kojeg uređaja tamburaši prije sviranja namještaju visinu tona?",
        "Which device do tambura players use to adjust their pitch before playing?",
        "elektronički ugađač",
    ),
    (
        "Kako se pokreti glumčevih ruku prenose na marionetu?",
        "How are the movements of an actor's hands transmitted to a marionette?",
        "tanke niti",
    ),
    (
        "Kakve trajne oznake pokazuju gdje završavaju izmjerene parcele?",
        "What permanent markers show where the surveyed plots end?",
        "betonski međaši",
    ),
    (
        "Zašto košarač prije rada potapa osušene šibe?",
        "Why does the basket maker soak dried willow rods before working?",
        "ne bi pucale",
    ),
]


def main() -> None:
    fixtures = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    english = [
        {"question": question, "expected_substring": answer}
        for question, answer in QUESTIONS
    ]
    croatian = [
        {"question": question, "question_en": translated, "expected_substring": answer}
        for question, translated, answer in QUESTIONS_HR
    ]
    for name, cases in (("eval.jsonl", english), ("eval_hr.jsonl", croatian)):
        rows = [json.dumps(case, ensure_ascii=name == "eval.jsonl") for case in cases]
        (fixtures / name).write_text(
            "\n".join(rows) + "\n", encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    main()
