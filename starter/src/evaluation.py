"""Automatic retrieval scoring (Hit@1, Evidence Hit@3) and per-query traces.

Only retrieval is scored here. Coherence, grounding and metadata correctness are
human labels collected in results/audit/ and are never inferred from string match.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


def squash(text: str) -> str:
    """Same rule as scripts/verify_benchmark.py: all whitespace runs -> one space."""
    return re.sub(r"\s+", " ", text).strip()


def _golds(question: dict[str, Any]) -> list[dict[str, Any]]:
    return [question] + list(question.get("alternative_evidence", []))


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """A retrieved chunk is an evidence hit when it comes from a gold
    (source, page) pair AND contains that pair's whole evidence quote.
    page_hit marks a gold page whose chunk lacks the full quote (e.g. split)."""
    golds = _golds(question)
    results = []
    for rank, h in enumerate(hits, start=1):
        text = squash(h["text"])
        same_page = [g for g in golds
                     if h["document_id"] == g["gold_source_id"] and h["page"] == g["gold_page"]]
        evidence_hit = any(squash(g["evidence_quote"]) in text for g in same_page)
        results.append({
            "rank": rank, "chunk_id": h["chunk_id"], "score": round(h["score"], 6),
            "source": h["source"], "page": h["page"], "chapter": h["chapter"],
            "section": h["section"], "evidence_hit": evidence_hit,
            "page_hit": bool(same_page), "text": h["text"],
        })
    flt = question.get("filter") or {}
    first = next((r["rank"] for r in results if r["evidence_hit"]), None)
    return {
        "id": question["id"], "split": question["split"], "type": question["type"],
        "question": question["question"], "filter": question.get("filter"),
        "gold": [{"source_id": g["gold_source_id"], "page": g["gold_page"],
                  "evidence_quote": g["evidence_quote"]} for g in golds],
        "hit_at_1": first == 1,
        "hit_at_3": first is not None and first <= 3,
        "first_hit_rank": first,
        # gold page retrieved but no chunk holds the full evidence
        "page_hit_only": first is None and any(r["page_hit"] for r in results[:3]),
        # whether every top-3 result satisfies the question's filter (None if no filter)
        "top3_filter_compliant": (all(r[k] == v for r in results[:3] for k, v in flt.items())
                                  if flt else None),
        "results": results,
    }


def _ratio(n: int, d: int) -> dict[str, Any]:
    return {"n": n, "N": d, "text": f"{n}/{d}", "rate": round(n / d, 4) if d else None}


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Hit@1 / Evidence Hit@3 as n/N per strategy x split, plus filter subsets."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
        groups[(t["strategy"], "all")].append(t)
    out: dict[str, Any] = {}
    for (strategy, split), ts in sorted(groups.items()):
        filt = [t for t in ts if t["filter"]]
        out.setdefault(strategy, {})[split] = {
            "hit_at_1": _ratio(sum(t["hit_at_1"] for t in ts), len(ts)),
            "hit_at_3": _ratio(sum(t["hit_at_3"] for t in ts), len(ts)),
            "page_hit_only": _ratio(sum(t["page_hit_only"] for t in ts), len(ts)),
            "filter_questions": {
                "hit_at_3": _ratio(sum(t["hit_at_3"] for t in filt), len(filt)),
                "top3_filter_compliant": (_ratio(sum(bool(t["top3_filter_compliant"]) for t in filt),
                                                 len(filt)) if filt else "N/A"),
            },
        }
    return out
