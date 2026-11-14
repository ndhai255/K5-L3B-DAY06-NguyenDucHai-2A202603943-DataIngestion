"""Day 06 pipeline: chunk -> embed -> store -> retrieve top-3 -> evaluate -> audit sheets.

Run from starter/ (after scripts/build_manifest.py and scripts/verify_benchmark.py):
    python -m src.run                    # ingest A/B/C, run all questions, write results/
    python -m src.run --reingest-check   # ingest twice, prove row counts do not change
    python -m src.run --overwrite-audit  # regenerate results/audit/*.csv (erases labels!)

Strategies (same corpus, model and questions):
    A  fixed_size(500, overlap 50), no filter
    B  by_paragraph(max 1000),      no filter
    C  identical chunks to B, metadata filter `chapter` applied only to questions
       that carry a `filter`; other questions run unfiltered (recorded in traces).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics as st
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import PRICE_PER_1M_TOKENS, OpenAIEmbedder
from .evaluation import evaluate_query, summarize
from .models import Chunk, DocumentPage
from .store import PgVectorStore

STARTER = Path(__file__).resolve().parents[1]
REPO = STARTER.parent
PAGES = STARTER / "data" / "processed" / "pages.jsonl"
MANIFEST = REPO / "data" / "manifest.json"
QUESTIONS = REPO / "benchmark" / "questions.jsonl"
RESULTS = STARTER / "results"
TOP_K = 3
MIN_PAGES = 30
COHERENCE_POSITIONS = 10

STRATEGIES = {
    "A": {"chunker": "fixed_size", "params": {"size": 500, "overlap": 50}, "use_filter": False},
    "B": {"chunker": "by_paragraph", "params": {"max_size": 1000}, "use_filter": False},
    "C": {"chunker": "by_paragraph", "params": {"max_size": 1000}, "use_filter": True},
}
CHUNKERS = {"fixed_size": fixed_size, "by_paragraph": by_paragraph}


# ---------------------------------------------------------------- loading
def load_pages() -> list[DocumentPage]:
    if not PAGES.exists():
        sys.exit(f"Missing {PAGES}; run scripts/build_manifest.py first.")
    pages = [DocumentPage(document_id=r["document_id"], source=r["source"], page=r["page"],
                          text=r["text"], metadata=r["metadata"])
             for r in map(json.loads, PAGES.read_text(encoding="utf-8").splitlines())]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    counted = {(s["source_id"], c["page"]) for s in manifest["sources"] for c in s["counted_pages"]}
    loaded = {(p.document_id, p.page) for p in pages}
    if loaded != counted:
        sys.exit("pages.jsonl does not match manifest counted_pages; rerun build_manifest.py.")
    if len(pages) < MIN_PAGES:
        sys.exit(f"Only {len(pages)} content pages; need >= {MIN_PAGES}.")
    return pages


def load_questions() -> list[dict]:
    return [json.loads(l) for l in QUESTIONS.read_text(encoding="utf-8").splitlines() if l.strip()]


def build_chunks(pages: list[DocumentPage]) -> dict[str, list[Chunk]]:
    out = {}
    for name, cfg in STRATEGIES.items():
        fn = CHUNKERS[cfg["chunker"]]
        out[name] = [c for p in pages for c in fn(p, **cfg["params"])]
    return out


# ---------------------------------------------------------------- ingest
def sync(store: PgVectorStore, embedder: OpenAIEmbedder, strategy: str,
         chunks: list[Chunk]) -> dict:
    """Idempotent ingest: write only new/changed chunks, embed only text whose
    vector is not stored yet, then delete chunks the chunker no longer produces."""
    t0 = time.perf_counter()
    tokens0 = embedder.total_tokens
    existing = store.existing_hashes(strategy)
    changed = [c for c in chunks if existing.get(c.chunk_id) != c.metadata["content_hash"]]
    reuse = store.vectors_by_hash([c.metadata["content_hash"] for c in changed])
    to_embed = {c.metadata["content_hash"]: c.text for c in changed
                if c.metadata["content_hash"] not in reuse}
    fresh = dict(zip(to_embed, embedder.embed_documents(list(to_embed.values())))) if to_embed else {}
    vectors = [reuse.get(h) or fresh[h] for h in (c.metadata["content_hash"] for c in changed)]
    if changed:
        store.upsert(strategy, changed, vectors)
    deleted = store.delete_obsolete(strategy, sorted({c.document_id for c in chunks}),
                                    {c.chunk_id for c in chunks})
    return {"chunks": len(chunks), "written": len(changed), "embedded_texts": len(to_embed),
            "reused_vectors": len(changed) - len(to_embed), "deleted_obsolete": deleted,
            "tokens": embedder.total_tokens - tokens0,
            "seconds": round(time.perf_counter() - t0, 3)}


def log_usage(phase: str, model: str, tokens: int) -> None:
    """Append API usage so the first (paid) ingest stays on record after reruns."""
    path = RESULTS / "embedding_usage.csv"
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "phase", "model", "tokens", "cost_usd"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), phase, model, tokens,
                    f"{tokens / 1e6 * PRICE_PER_1M_TOKENS[model]:.6f}"])


def ingest_all(store, embedder, chunks) -> dict:
    return {name: sync(store, embedder, name, chunks[name]) for name in STRATEGIES}


# ---------------------------------------------------------------- audit sheets
def _write_csv(path: Path, fields: list[str], rows: list[dict], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        print(f"  keep existing {os.path.relpath(path, STARTER)} (may hold your labels; "
              f"use --overwrite-audit to regenerate)")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {os.path.relpath(path, STARTER)} ({len(rows)} rows)")


def write_audit(pages, chunks, traces, questions, overwrite: bool) -> None:
    audit = RESULTS / "audit"
    audit.mkdir(parents=True, exist_ok=True)

    # Coherence: the same 10 source positions for every strategy: the middle
    # character of each of the first 10 counted pages.
    rows = []
    for pos_id, p in enumerate(sorted(pages, key=lambda p: p.page)[:COHERENCE_POSITIONS], 1):
        offset = len(p.text) // 2
        for name in STRATEGIES:
            on_page = [c for c in chunks[name] if c.page == p.page]
            chunk = next((c for c in on_page
                          if c.metadata["char_start"] <= offset < c.metadata["char_end"]), None) \
                or next(c for c in on_page if c.metadata["char_start"] >= offset)
            rows.append({"position_id": pos_id, "page": p.page, "offset": offset,
                         "strategy": name, "chunk_id": chunk.chunk_id,
                         "chunk_chars": len(chunk.text), "chunk_text": chunk.text,
                         "note": "same chunk as B" if name == "C" else "",
                         "score_0_2": "", "reason": ""})
    _write_csv(audit / "coherence.csv", list(rows[0]), rows, overwrite)

    test_ids = [q["id"] for q in questions if q["split"] == "test"]
    by_key = {(t["strategy"], t["id"]): t for t in traces}
    qmap = {q["id"]: q for q in questions}

    # Grounding: one score per (test question, strategy) for its top-3 as a whole.
    rows = []
    for qid in test_ids:
        for name in STRATEGIES:
            t = by_key[(name, qid)]
            row = {"id": qid, "strategy": name, "question": t["question"],
                   "filter_applied": json.dumps(t["filter_applied"]) if t["filter_applied"] else "",
                   "expected_answer": qmap[qid]["expected_answer"]}
            for r in t["results"]:
                row[f"top{r['rank']}_ref"] = f"p{r['page']} {r['chunk_id']}"
                row[f"top{r['rank']}_text"] = r["text"]
            row.update({"score_0_2": "", "reason": ""})
            rows.append(row)
    fields = ["id", "strategy", "question", "filter_applied", "expected_answer"] + \
        [f"top{i}_{k}" for i in range(1, TOP_K + 1) for k in ("ref", "text")] + ["score_0_2", "reason"]
    _write_csv(audit / "grounding.csv", fields, rows, overwrite)

    # Metadata: every top-3 record of every test question; verify against the PDF.
    rows = []
    for qid in test_ids:
        for name in STRATEGIES:
            t = by_key[(name, qid)]
            flt = qmap[qid].get("filter") or {}
            for r in t["results"]:
                rows.append({
                    "id": qid, "strategy": name, "rank": r["rank"], "chunk_id": r["chunk_id"],
                    "source": r["source"], "page": r["page"], "chapter": r["chapter"],
                    "section": r["section"], "text_preview": r["text"][:200],
                    "question_filter": json.dumps(flt) if flt else "",
                    "filter_applied": json.dumps(t["filter_applied"]) if t["filter_applied"] else "",
                    "filter_ok_auto": (all(r[k] == v for k, v in flt.items()) if flt else "N/A"),
                    "metadata_correct_1_0": "", "error_note": ""})
    _write_csv(audit / "metadata.csv", list(rows[0]), rows, overwrite)


# ---------------------------------------------------------------- main
def _length_stats(chunks: list[Chunk]) -> dict:
    L = sorted(len(c.text) for c in chunks)
    q = st.quantiles(L, n=4)
    return {"min": L[0], "p25": q[0], "median": st.median(L), "mean": round(st.mean(L), 1),
            "p75": q[2], "max": L[-1]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reingest-check", action="store_true")
    ap.add_argument("--overwrite-audit", action="store_true")
    args = ap.parse_args(argv)

    load_dotenv(STARTER / ".env")
    model = os.getenv("EMBEDDING_MODEL") or sys.exit("EMBEDDING_MODEL missing in starter/.env")
    db_url = os.getenv("DATABASE_URL") or sys.exit("DATABASE_URL missing in starter/.env")

    pages = load_pages()
    questions = load_questions()
    chunks = build_chunks(pages)
    embedder = OpenAIEmbedder(model)
    store = PgVectorStore(db_url, embedder.dimensions)
    store.create_schema()
    RESULTS.mkdir(exist_ok=True)

    print(f"{len(pages)} pages, {len(questions)} questions, model {model} ({embedder.dimensions}d)")
    ingest = ingest_all(store, embedder, chunks)
    log_usage("ingest", model, sum(r["tokens"] for r in ingest.values()))
    for name, r in ingest.items():
        print(f"  ingest {name}: {r}")

    if args.reingest_check:
        before = store.count()
        again = ingest_all(store, embedder, chunks)
        after = store.count()
        report = {"checked_at": datetime.now().isoformat(timespec="seconds"),
                  "rows_before": before, "rows_after": after, "second_ingest": again,
                  "expected_rows": {n: len(c) for n, c in chunks.items()}}
        ok = (before == after == report["expected_rows"]
              and all(r["written"] == 0 and r["tokens"] == 0 and r["deleted_obsolete"] == 0
                      for r in again.values()))
        report["passed"] = ok
        (RESULTS / "reingest_check.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"rows before {before} | after {after} | second pass wrote "
              f"{sum(r['written'] for r in again.values())}, embedded "
              f"{sum(r['embedded_texts'] for r in again.values())}")
        sys.exit(0 if ok else "Re-ingest check FAILED, see results/reingest_check.json")

    # One query embedding per question, shared by all strategies.
    tokens0 = embedder.total_tokens
    qvecs = dict(zip([q["id"] for q in questions],
                     embedder.embed_documents([q["question"] for q in questions])))
    query_tokens = embedder.total_tokens - tokens0
    log_usage("queries", model, query_tokens)

    traces, latency = [], {}
    for name, cfg in STRATEGIES.items():
        latency[name] = []
        for q in questions:
            filters = q["filter"] if cfg["use_filter"] and q.get("filter") else None
            t0 = time.perf_counter()
            hits = store.search(name, qvecs[q["id"]], top_k=TOP_K, filters=filters)
            ms = (time.perf_counter() - t0) * 1000
            latency[name].append(ms)
            trace = evaluate_query(q, hits)
            trace.update({"strategy": name, "filter_applied": filters,
                          "latency_ms": round(ms, 2)})
            traces.append(trace)

    with (RESULTS / "traces.jsonl").open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    summary = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "model": model, "top_k": TOP_K,
               "strategies": {n: {k: v for k, v in c.items()} for n, c in STRATEGIES.items()},
               "metrics": summarize(traces)}
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    doc_tokens = sum(r["tokens"] for r in ingest.values())
    stats = {
        "generated_at": summary["generated_at"],
        "model": model, "dimensions": embedder.dimensions,
        "price_usd_per_1m_tokens": PRICE_PER_1M_TOKENS[model],
        "vector_search": "exact cosine (embedding <=> query), no ANN index",
        "corpus": {"counted_pages": len(pages), "chars": sum(len(p.text) for p in pages)},
        "strategies": {n: {**STRATEGIES[n], "chunks": len(chunks[n]),
                           "chunk_chars": _length_stats(chunks[n]), "ingest": ingest[n]}
                       for n in STRATEGIES},
        "db_rows": store.count(),
        "this_run": {"document_tokens": doc_tokens, "query_tokens": query_tokens,
                     "cost_usd": round((doc_tokens + query_tokens) / 1e6
                                       * PRICE_PER_1M_TOKENS[model], 6),
                     "api_calls": embedder.api_calls,
                     "note": "unchanged chunks are not re-embedded; the first ingest's "
                             "cost is kept in results/embedding_usage.csv"},
        "query_latency_ms": {n: {"mean": round(st.mean(v), 2), "median": round(st.median(v), 2),
                                 "max": round(max(v), 2)} for n, v in latency.items()},
    }
    (RESULTS / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n")

    write_audit(pages, chunks, traces, questions, args.overwrite_audit)
    for name, m in summary["metrics"].items():
        print(f"  {name}: " + " | ".join(f"{s} Hit@1 {m[s]['hit_at_1']['text']} "
                                          f"Hit@3 {m[s]['hit_at_3']['text']}"
                                          for s in ("dev", "test")))


if __name__ == "__main__":
    main()
