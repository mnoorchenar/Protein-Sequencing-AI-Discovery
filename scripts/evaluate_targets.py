"""Measure how often AI-suggested protein IDs survive UniProt verification.

Needs GROQ_API_KEY or HF_TOKEN, and network access. Run from the repo root:

    python -m scripts.evaluate_targets

Each suggestion gets one outcome:
    confirmed  The model's ID matched the protein it named.
    corrected  The ID was wrong, but UniProt found the named protein.
    dropped    UniProt couldn't confirm the protein, so the app wouldn't show it.

Outcomes rely on the app's name matching, not on review by a person.
"""

import json
import logging
import time
from datetime import date
from pathlib import Path

from services import config, llm, prompts, uniprot

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "evaluation.json"
SECONDS_BETWEEN_QUERIES = 4

QUERIES = [
    "Alzheimer's disease",
    "Parkinson's disease",
    "type 2 diabetes",
    "lung cancer",
    "breast cancer",
    "colorectal cancer",
    "melanoma",
    "acute myeloid leukemia",
    "rheumatoid arthritis",
    "psoriasis",
    "Crohn's disease",
    "asthma",
    "hypertension",
    "heart failure",
    "obesity",
    "osteoporosis",
    "major depressive disorder",
    "multiple sclerosis",
    "cystic fibrosis",
    "HIV host factors",
]


def classify(target):
    record = uniprot.resolve_target(target)
    if not record:
        return "dropped", None
    outcome = "confirmed" if record["uniprot_id"] == target["uniprot_id"] else "corrected"
    return outcome, record["uniprot_id"]


def main():
    logging.basicConfig(level=logging.WARNING)
    model = config.model_ids()[0]
    rows = []
    for query in QUERIES:
        try:
            text, used = llm.complete(
                prompts.TARGETS_SYSTEM, f"Research query: {query}", model=model
            )
        except llm.LLMUnavailable as error:
            print(f"{query}: skipped ({error})")
            time.sleep(SECONDS_BETWEEN_QUERIES)
            continue

        targets, _ = llm.parse_targets(text)
        for target in targets:
            outcome, resolved = classify(target)
            rows.append(
                {
                    "query": query,
                    "model": used,
                    "name": target["name"],
                    "suggested_id": target["uniprot_id"],
                    "resolved_id": resolved,
                    "outcome": outcome,
                }
            )
        print(f"{query}: {len(targets)} suggestions, answered by {used}")
        time.sleep(SECONDS_BETWEEN_QUERIES)

    outcomes = ("confirmed", "corrected", "dropped")
    summary = {name: sum(row["outcome"] == name for row in rows) for name in outcomes}
    report = {
        "date": date.today().isoformat(),
        "queries_answered": len({row["query"] for row in rows}),
        "queries_total": len(QUERIES),
        "suggestions": len(rows),
        "summary": summary,
        "rows": rows,
    }
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in report if key != "rows"}, indent=2))


if __name__ == "__main__":
    main()
