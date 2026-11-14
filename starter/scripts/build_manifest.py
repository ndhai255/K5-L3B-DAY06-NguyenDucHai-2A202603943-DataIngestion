"""Build the corpus manifest, normalized pages and ingest log.

Run from starter/:  python scripts/build_manifest.py [--chapters 4 5 6]

Outputs
  ../data/manifest.json            source, licence, counted/excluded pages, counting rule
  data/processed/pages.jsonl       normalized text + metadata of every counted page
  results/ingest_log.csv           one row per physical page: ok / excluded / empty / error

Chapter and section metadata come from the PDF's own outline (bookmarks), never
from guesses. Page numbers are 1-based PDF page indices, not printed page numbers.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from pypdf import PdfReader

STARTER = Path(__file__).resolve().parents[1]
REPO = STARTER.parent
sys.path.insert(0, str(STARTER))

from src.ingestion import load_pdf, normalize_text, strip_page_furniture  # noqa: E402

DOCUMENT_ID = "openstax-intro-python"
TITLE = "Introduction to Python Programming (OpenStax)"
PDF_PATH = STARTER / "data" / "raw" / "Introduction_to_Python_Programming-WEB.pdf"
PDF_URL = ("https://assets.openstax.org/oscms-prodcms/media/documents/"
           "Introduction_to_Python_Programming-WEB.pdf")
BOOK_URL = "https://openstax.org/details/books/introduction-python-programming"
LICENSE = "CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/)"
ATTRIBUTION = ("Udayan Das, Aubrey Lawson, Chris Mayfield, Narges Norouzi. "
               "Introduction to Python Programming. OpenStax, Rice University. "
               "Access for free at openstax.org.")
MIN_CONTENT_CHARS = 300
MIN_COUNTED_PAGES = 30
CHAPTER_RE = re.compile(r"^Chapter (\d+) (.+)$")


def read_outline(reader: PdfReader) -> list[dict]:
    """Return chapters with their sections, using PDF bookmark destinations."""
    chapters: list[dict] = []

    def walk(items, depth=0, current=None):
        for item in items:
            if isinstance(item, list):
                walk(item, depth + 1, chapters[-1] if chapters else None)
                continue
            page = reader.get_destination_page_number(item) + 1
            m = CHAPTER_RE.match(item.title) if depth == 0 else None
            if m:
                chapters.append({"chapter": int(m.group(1)), "title": m.group(2),
                                 "start": page, "sections": []})
            elif depth == 1 and current is not None:
                current["sections"].append({"title": item.title, "start": page})

    walk(reader.outline)
    # A chapter ends one page before the next top-level bookmark.
    top_starts = sorted({reader.get_destination_page_number(i) + 1
                         for i in reader.outline if not isinstance(i, list)})
    for ch in chapters:
        later = [s for s in top_starts if s > ch["start"]]
        ch["end"] = (later[0] - 1) if later else len(reader.pages)
    return chapters


def sections_on_page(chapter: dict, page: int) -> list[str]:
    """Sections whose span touches this page (a section may start mid-page)."""
    secs = chapter["sections"]
    out = []
    for i, sec in enumerate(secs):
        nxt = secs[i + 1]["start"] if i + 1 < len(secs) else chapter["end"]
        if sec["start"] <= page <= nxt and sec["title"] != "Chapter Outline":
            out.append(sec["title"])
    return out


def strip_chapter_opener(text: str, chapter: dict) -> str:
    """Opening pages end with the chapter title and number as decoration."""
    lines = text.rstrip().split("\n")
    while lines and lines[-1].strip() in {chapter["title"], str(chapter["chapter"]), ""}:
        lines.pop()
    return "\n".join(lines)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapters", type=int, nargs="+", default=[4, 5, 6])
    args = parser.parse_args()

    if not PDF_PATH.exists():
        sys.exit(f"Missing {PDF_PATH}. Download it first:\n  curl -L -o {PDF_PATH} {PDF_URL}")

    reader = PdfReader(str(PDF_PATH))
    outline = {c["chapter"]: c for c in read_outline(reader)}
    missing = [c for c in args.chapters if c not in outline]
    if missing:
        sys.exit(f"Chapters not found in PDF outline: {missing}")

    source = f"data/raw/{PDF_PATH.name}"
    counted, excluded, log_rows, page_records = [], [], [], []
    for ch_no in args.chapters:
        ch = outline[ch_no]
        pages, log = load_pdf(PDF_PATH, DOCUMENT_ID, source,
                              list(range(ch["start"], ch["end"] + 1)))
        for row in log:
            log_rows.append({**row, "chapter": ch_no, "raw_chars": 0, "content_chars": 0})
            excluded.append({"page": row["page"], "chapter": ch_no,
                             "reason": f"{row['status']}: {row['detail']}"})
        for p in pages:
            text = strip_page_furniture(p.text)
            if p.page == ch["start"]:
                text = strip_chapter_opener(text, ch)
            text = normalize_text(text)
            base = {"document_id": DOCUMENT_ID, "page": p.page, "chapter": ch_no,
                    "raw_chars": p.metadata["raw_chars"], "content_chars": len(text)}
            if len(text) < MIN_CONTENT_CHARS:
                reason = f"only {len(text)} content chars after normalization (< {MIN_CONTENT_CHARS})"
                excluded.append({"page": p.page, "chapter": ch_no, "reason": reason})
                log_rows.append({**base, "status": "excluded", "detail": reason})
                continue
            secs = sections_on_page(ch, p.page)
            counted.append({"page": p.page, "chapter": ch_no, "chars": len(text)})
            log_rows.append({**base, "status": "ok", "detail": ""})
            page_records.append({
                "document_id": DOCUMENT_ID, "source": source, "page": p.page,
                "text": text,
                "metadata": {"chapter": ch_no, "chapter_title": ch["title"],
                             "sections": secs},
            })

    if len(counted) < MIN_COUNTED_PAGES:
        sys.exit(f"Only {len(counted)} counted pages; need >= {MIN_COUNTED_PAGES}.")

    accessed = date.fromtimestamp(PDF_PATH.stat().st_mtime).isoformat()
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generated_by": "starter/scripts/build_manifest.py",
        "counting_rule": (
            "A page counts when, after removing running headers/footers and the chapter-opener "
            f"title decoration and normalizing whitespace, it has >= {MIN_CONTENT_CHARS} characters "
            "of text. Pages are 1-based PDF page indices (the printed page number is 10 lower). "
            "Only the selected chapters are in scope; front matter, other chapters and index "
            "are not ingested."
        ),
        "filter_field": {
            "name": "chapter", "type": "int",
            "values_source": "PDF outline (bookmarks) 'Chapter N <title>'; a page belongs to the "
                             "chapter whose bookmark range contains it",
        },
        "sources": [{
            "source_id": DOCUMENT_ID,
            "title": TITLE,
            "source_path_or_url": PDF_URL,
            "book_page": BOOK_URL,
            "local_path": f"starter/{source}",
            "license_or_permission": LICENSE,
            "attribution": ATTRIBUTION,
            "redistribution_note": (
                "The licence requires 'Access for free at openstax.org.' on every redistributed "
                "page view. The pipeline strips that footer from chunk text, so the raw PDF and "
                "starter/data/processed/ are git-ignored; reproduce them with the commands below. "
                "Short excerpts in benchmark/results keep this attribution in their README."
            ),
            "reproduce": [
                f"curl -L -o starter/{source} {PDF_URL}",
                "cd starter && python scripts/build_manifest.py",
            ],
            "accessed_at": accessed,
            "version": f"PDF /ModDate {reader.metadata.get('/ModDate', 'unknown')}",
            "sha256": sha256(PDF_PATH),
            "physical_pages_in_pdf": len(reader.pages),
            "chapters": [{"chapter": c, "title": outline[c]["title"],
                          "pdf_pages": [outline[c]["start"], outline[c]["end"]],
                          "sections": [s["title"] for s in outline[c]["sections"]
                                       if s["title"] != "Chapter Outline"]}
                         for c in args.chapters],
            "pages_in_scope": sum(outline[c]["end"] - outline[c]["start"] + 1 for c in args.chapters),
            "counted_pages": counted,
            "excluded_pages": excluded,
            "counted_page_total": len(counted),
            "counted_char_total": sum(c["chars"] for c in counted),
        }],
    }

    (REPO / "data").mkdir(exist_ok=True)
    (REPO / "data" / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    processed = STARTER / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    with (processed / "pages.jsonl").open("w") as f:
        for rec in page_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    results = STARTER / "results"
    results.mkdir(exist_ok=True)
    with (results / "ingest_log.csv").open("w", newline="") as f:
        fields = ["document_id", "page", "chapter", "status", "raw_chars", "content_chars", "detail"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in sorted(log_rows, key=lambda r: r["page"]):
            w.writerow({k: row.get(k, "") for k in fields})

    per_ch = {c: sum(1 for x in counted if x["chapter"] == c) for c in args.chapters}
    print(f"Counted pages: {len(counted)} {per_ch} | excluded: {len(excluded)} | "
          f"chars: {manifest['sources'][0]['counted_char_total']}")
    for e in excluded:
        print(f"  excluded p{e['page']} (ch{e['chapter']}): {e['reason']}")


if __name__ == "__main__":
    main()
