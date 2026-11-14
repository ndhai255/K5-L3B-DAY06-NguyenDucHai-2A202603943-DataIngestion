"""Verify benchmark/questions.jsonl against the normalized corpus before any retrieval run.

Checks, per question:
  * required fields and split values;
  * every evidence quote (gold + alternatives) occurs on its gold page of
    data/processed/pages.jsonl, compared after collapsing whitespace (PDF line
    breaks inside a sentence are not content);
  * filter keys/values exist in page metadata and the gold page satisfies the filter;
  * split counts (>=15 dev, >=5 test) and filter counts (>=3 total, >=1 test).

Run from starter/:  python scripts/verify_benchmark.py
Exit code 1 if any check fails.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

STARTER = Path(__file__).resolve().parents[1]
PAGES = STARTER / "data" / "processed" / "pages.jsonl"
QUESTIONS = STARTER.parent / "benchmark" / "questions.jsonl"
REQUIRED = ["id", "split", "type", "question", "expected_answer",
            "gold_source_id", "gold_page", "evidence_quote", "filter"]


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    pages = {}
    for line in PAGES.read_text(encoding="utf-8").splitlines():
        p = json.loads(line)
        pages[(p["document_id"], p["page"])] = p
    questions = [json.loads(l) for l in QUESTIONS.read_text(encoding="utf-8").splitlines() if l.strip()]

    errors: list[str] = []
    ids = Counter(q.get("id") for q in questions)
    errors += [f"duplicate id {i}" for i, n in ids.items() if n > 1]

    for q in questions:
        qid = q.get("id", "?")
        missing = [k for k in REQUIRED if k not in q]
        if missing:
            errors.append(f"{qid}: missing fields {missing}")
            continue
        if q["split"] not in ("dev", "test"):
            errors.append(f"{qid}: bad split {q['split']!r}")
        evidences = [q] + q.get("alternative_evidence", [])
        for ev in evidences:
            page = pages.get((ev["gold_source_id"], ev["gold_page"]))
            if page is None:
                errors.append(f"{qid}: page {ev['gold_page']} not in corpus")
                continue
            if squash(ev["evidence_quote"]) not in squash(page["text"]):
                errors.append(f"{qid}: evidence not found on page {ev['gold_page']}")
            for key, value in (q["filter"] or {}).items():
                if key not in page["metadata"]:
                    errors.append(f"{qid}: filter key {key!r} not in page metadata")
                elif page["metadata"][key] != value:
                    errors.append(f"{qid}: gold page {ev['gold_page']} has {key}="
                                  f"{page['metadata'][key]!r}, filter wants {value!r}")

    splits = Counter(q["split"] for q in questions)
    filtered = Counter(q["split"] for q in questions if q.get("filter"))
    if splits["dev"] < 15 or splits["test"] < 5:
        errors.append(f"need >=15 dev / >=5 test, have {dict(splits)}")
    if sum(filtered.values()) < 3 or filtered["test"] < 1:
        errors.append(f"need >=3 filter questions with >=1 in test, have {dict(filtered)}")

    print(f"questions: {len(questions)}  splits: {dict(splits)}  "
          f"with filter: {dict(filtered)}  types: {dict(Counter(q['type'] for q in questions))}")
    for e in errors:
        print("FAIL", e)
    print("Benchmark OK" if not errors else f"{len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
