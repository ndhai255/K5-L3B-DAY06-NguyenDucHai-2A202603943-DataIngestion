"""Read and normalize source data."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .models import DocumentPage

# Running headers/footers printed on every OpenStax page. They carry no content
# and would otherwise be repeated inside many chunks.
_FURNITURE_PATTERNS = [
    re.compile(r"^Access for free at openstax\.org$"),
    # even pages: "86     4 • Decisions"
    re.compile(r"^\d+\s+\d+\s*•\s*.+$"),
    # odd pages: "4.8 • Chapter summary     111"
    re.compile(r"^\d+(\.\d+)?\s*•\s*.+?\s+\d+$"),
]


def load_pdf(path: Path, document_id: str, source: str,
             pages: list[int] | None = None) -> tuple[list[DocumentPage], list[dict[str, Any]]]:
    """Extract each physical page; keep its 1-based PDF page number and source.

    Returns (pages, log). Pages with no extractable text or an extraction error are
    not returned as content but are recorded in the log. OCR is out of scope: this
    corpus is born-digital.
    """
    reader = PdfReader(str(path))
    wanted = pages or list(range(1, len(reader.pages) + 1))
    result: list[DocumentPage] = []
    log: list[dict[str, Any]] = []
    for page_no in wanted:
        if not 1 <= page_no <= len(reader.pages):
            log.append({"document_id": document_id, "page": page_no,
                        "status": "error", "detail": "page out of range"})
            continue
        try:
            raw = reader.pages[page_no - 1].extract_text() or ""
        except Exception as exc:  # pypdf raises several exception types
            log.append({"document_id": document_id, "page": page_no,
                        "status": "error", "detail": f"{type(exc).__name__}: {exc}"})
            continue
        if not raw.strip():
            log.append({"document_id": document_id, "page": page_no,
                        "status": "empty", "detail": "no extractable text"})
            continue
        result.append(DocumentPage(document_id=document_id, source=source,
                                   page=page_no, text=raw,
                                   metadata={"raw_chars": len(raw)}))
    return result, log


def strip_page_furniture(text: str) -> str:
    """Drop running header/footer lines (OpenStax layout)."""
    kept = [line for line in text.split("\n")
            if not any(p.match(line.strip()) for p in _FURNITURE_PATTERNS)]
    return "\n".join(kept)


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace without discarding useful structure.

    - NFKC folds compatibility characters (ligatures, full-width forms, NBSP).
    - Repeated spaces inside a line collapse to one; trailing spaces go; leading
      indentation is kept because code listings depend on it.
    - Line breaks are kept (code listings and paragraph detection need them);
      runs of 3+ newlines collapse to a single blank line.
    - A line break right after a word-final hyphen is removed but the hyphen is
      KEPT. In the counted pages every such break (12/12) falls inside a URL slug,
      e.g. ".../4-2-if-\\nelse-statements"; no prose word is hyphenated across lines.
      Classic de-hyphenation (dropping the hyphen) would corrupt those URLs into
      "ifelse", while leaving the break would split one URL across two lines.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", "    ")
    text = "".join(ch for ch in text
                   if ch == "\n" or unicodedata.category(ch)[0] != "C")
    lines = []
    for line in text.split("\n"):
        indent = len(line) - len(line.lstrip(" "))  # keep code indentation
        body = re.sub(r" {2,}", " ", line.strip())
        lines.append((" " * indent + body) if body else "")
    text = "\n".join(lines)
    text = re.sub(r"(?<=\w)-\n *(?=\S)", "-", text)  # rejoin, keep the hyphen
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
