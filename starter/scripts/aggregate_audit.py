"""Aggregate the human audit labels in results/audit/ (filled in by hand).

Run from starter/:  python scripts/aggregate_audit.py
Writes results/audit_summary.json. Unlabelled rows are counted and reported,
never treated as 0 or as correct.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1] / "results" / "audit"
OUT = AUDIT.parent / "audit_summary.json"


def read(name: str) -> list[dict]:
    path = AUDIT / name
    if not path.exists():
        raise SystemExit(f"Missing {path}; run python -m src.run first.")
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def score_table(rows: list[dict], label: str) -> dict:
    """Counts of 0/1/2 and mean/2 per strategy, from column score_0_2."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["strategy"]].append(r)
    out = {}
    for strategy, rs in sorted(by.items()):
        scored = [r for r in rs if r["score_0_2"].strip() != ""]
        bad = [r for r in scored if r["score_0_2"].strip() not in {"0", "1", "2"}]
        if bad:
            raise SystemExit(f"{label}: score_0_2 must be 0, 1 or 2; got {bad[0]['score_0_2']!r}")
        vals = [int(r["score_0_2"]) for r in scored]
        missing_reason = sum(1 for r in scored if not r["reason"].strip())
        out[strategy] = {
            "labelled": f"{len(scored)}/{len(rs)}",
            "counts": {str(k): Counter(vals).get(k, 0) for k in (0, 1, 2)},
            "mean_over_2": round(sum(vals) / len(vals), 3) if vals else None,
            "rows_without_reason": missing_reason,
        }
    return out


def metadata_table(rows: list[dict]) -> dict:
    yes, no = {"1", "y", "yes", "true", "dung", "đúng"}, {"0", "n", "no", "false", "sai"}
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["strategy"]].append(r)
    out = {}
    for strategy, rs in sorted(by.items()):
        labels = [r["metadata_correct_1_0"].strip().lower() for r in rs]
        unknown = [l for l in labels if l and l not in yes | no]
        if unknown:
            raise SystemExit(f"metadata.csv: metadata_correct_1_0 must be 1 or 0; got {unknown[0]!r}")
        labelled = [l for l in labels if l]
        correct = sum(l in yes for l in labelled)
        # filter compliance per question: all of its top-3 records satisfy the filter
        per_q: dict[str, list[str]] = defaultdict(list)
        for r in rs:
            if r["question_filter"]:
                per_q[r["id"]].append(r["filter_ok_auto"])
        compliant = sum(all(v == "True" for v in vs) for vs in per_q.values())
        out[strategy] = {
            "metadata_correct": f"{correct}/{len(labelled)}",
            "labelled": f"{len(labelled)}/{len(rs)}",
            "errors": [{"id": r["id"], "rank": r["rank"], "chunk_id": r["chunk_id"],
                        "note": r["error_note"]}
                       for r in rs if r["metadata_correct_1_0"].strip().lower() in no],
            "filter_compliance": (f"{compliant}/{len(per_q)}" if per_q else "N/A"),
        }
    return out


def main() -> None:
    summary = {
        "coherence": score_table(read("coherence.csv"), "coherence.csv"),
        "grounding": score_table(read("grounding.csv"), "grounding.csv"),
        "metadata": metadata_table(read("metadata.csv")),
    }
    OUT.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for dim in ("coherence", "grounding"):
        for s, v in summary[dim].items():
            print(f"{dim:9} {s}: mean {v['mean_over_2']}/2  counts {v['counts']}  labelled {v['labelled']}")
    for s, v in summary["metadata"].items():
        print(f"metadata  {s}: correct {v['metadata_correct']}  labelled {v['labelled']}  "
              f"filter compliance {v['filter_compliance']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
