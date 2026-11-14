"""Fixed-size (strategy A) and structure-aware paragraph (strategy B) chunking.

Both strategies chunk one page at a time, so every chunk maps to exactly one
physical PDF page. A chunk's text is always an exact slice
page.text[char_start:char_end], which keeps offsets truthful for audits.
"""
from __future__ import annotations

import hashlib
import re

from .models import Chunk, DocumentPage

# pypdf emits no blank lines between paragraphs in this corpus (0 "\n\n" in 76
# pages), so paragraphs are recovered from line widths. Prose lines are wrapped by
# the PDF layout at ~100-126 chars, while headings, code, list items and the last
# line of a paragraph are shorter. A line of >= SOFT_WRAP_MIN chars therefore
# continues onto the next line; a shorter one ends a block.
SOFT_WRAP_MIN = 90
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _make_chunk(page: DocumentPage, strategy: str, idx: int,
                start: int, end: int) -> Chunk:
    text = page.text[start:end]
    meta = page.metadata
    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page}:{strategy}:{idx}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata={
            "strategy": strategy,
            "chapter": meta.get("chapter"),
            "chapter_title": meta.get("chapter_title"),
            "sections": list(meta.get("sections", [])),
            "char_start": start,
            "char_end": end,
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
    )


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink [start, end) so it neither starts nor ends with whitespace."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _fixed_spans(text: str, start: int, stop: int, size: int,
                 overlap: int) -> list[tuple[int, int]]:
    """Character windows over text[start:stop], preferring whitespace cuts."""
    spans: list[tuple[int, int]] = []
    pos = start
    while pos < stop:
        end = min(pos + size, stop)
        if end < stop:
            # cut at the last whitespace in the second half of the window
            cut = max(text.rfind(" ", pos + size // 2, end),
                      text.rfind("\n", pos + size // 2, end))
            if cut > pos:
                end = cut
        s, e = _trim(text, pos, end)
        if e > s:
            spans.append((s, e))
        if end >= stop:
            break
        nxt = max(end - overlap, pos + 1)
        # do not start the next window in the middle of a word
        while nxt < end and not text[nxt - 1].isspace():
            nxt += 1
        pos = nxt
    return spans


def fixed_size(page: DocumentPage, size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Strategy A: sliding character windows of <= size chars with ~overlap chars
    shared between neighbours. Cuts snap back to the nearest whitespace so words
    are not split; the overlap start snaps forward to a word boundary."""
    if not 0 <= overlap < size:
        raise ValueError("need 0 <= overlap < size")
    spans = _fixed_spans(page.text, 0, len(page.text), size, overlap)
    return [_make_chunk(page, "fixed", i, s, e) for i, (s, e) in enumerate(spans)]


def _blocks(text: str) -> list[tuple[int, int]]:
    """Paragraph-like blocks: runs of soft-wrapped lines, ended by a short line."""
    blocks: list[tuple[int, int]] = []
    block_start = 0
    pos = 0
    for line in text.split("\n"):
        line_end = pos + len(line)
        if len(line.rstrip()) < SOFT_WRAP_MIN:
            s, e = _trim(text, block_start, line_end)
            if e > s:
                blocks.append((s, e))
            block_start = line_end + 1
        pos = line_end + 1
    s, e = _trim(text, block_start, len(text))
    if e > s:
        blocks.append((s, e))
    return blocks


def _split_oversized(text: str, start: int, end: int,
                     max_size: int) -> list[tuple[int, int]]:
    """Split one block longer than max_size at sentence ends; a single sentence
    that is still too long falls back to whitespace windows without overlap."""
    pieces: list[tuple[int, int]] = []
    cur_start = start
    last_ok = None  # end of the last sentence that still fits
    for m in _SENTENCE_END.finditer(text, start, end):
        sent_end = m.start()
        if sent_end - cur_start <= max_size:
            last_ok = sent_end
            continue
        if last_ok is not None:
            pieces.append((cur_start, last_ok))
            cur_start = _trim(text, last_ok, end)[0]
            last_ok = sent_end if sent_end - cur_start <= max_size else None
        if last_ok is None:  # one sentence alone exceeds max_size
            pieces.extend(_fixed_spans(text, cur_start, sent_end, max_size, 0))
            cur_start = _trim(text, sent_end, end)[0]
    if end - cur_start <= max_size:
        pieces.append((cur_start, end))
    else:
        if last_ok is not None:
            pieces.append((cur_start, last_ok))
            cur_start = _trim(text, last_ok, end)[0]
        pieces.extend(_fixed_spans(text, cur_start, end, max_size, 0))
    return [_trim(text, s, e) for s, e in pieces if e > s]


def by_paragraph(page: DocumentPage, max_size: int = 1000) -> list[Chunk]:
    """Strategy B: pack consecutive paragraph blocks into chunks of <= max_size
    chars, cutting only between blocks. A block longer than max_size is split at
    sentence boundaries first. No overlap."""
    text = page.text
    units: list[tuple[int, int]] = []
    for s, e in _blocks(text):
        units.extend([(s, e)] if e - s <= max_size else _split_oversized(text, s, e, max_size))

    spans: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = None
    for s, e in units:
        if cur is None:
            cur = (s, e)
        elif e - cur[0] <= max_size:
            cur = (cur[0], e)
        else:
            spans.append(cur)
            cur = (s, e)
    if cur is not None:
        spans.append(cur)
    return [_make_chunk(page, "paragraph", i, s, e) for i, (s, e) in enumerate(spans)]
