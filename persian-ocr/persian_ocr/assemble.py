"""Stitch tiles into pages and pages into a document.

Two seams have to be repaired:

* **tile seams** — consecutive tiles overlap on purpose, so the same lines are
  transcribed twice and a paragraph is usually cut in the middle;
* **page seams** — books routinely run a paragraph across a page break, and a
  page number sits between the two halves.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .engines.base import Block
from .normalize import fold_for_compare

SENTENCE_END = "؟!.…:»"
MIN_OVERLAP_WORDS = 3
MAX_OVERLAP_WORDS = 120


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, fold_for_compare(a), fold_for_compare(b), autojunk=False).ratio()


def _folded_words(text: str) -> List[str]:
    return fold_for_compare(text).split()


def find_overlap(a: str, b: str) -> int:
    """Longest suffix of `a` that is also a prefix of `b`, counted in words."""
    a_words, b_words = _folded_words(a), _folded_words(b)
    limit = min(len(a_words), len(b_words), MAX_OVERLAP_WORDS)
    for size in range(limit, MIN_OVERLAP_WORDS - 1, -1):
        if a_words[-size:] == b_words[:size]:
            return size
    return 0


def splice(a: str, b: str) -> Optional[str]:
    """Join two halves of the same paragraph read from overlapping tiles."""
    overlap = find_overlap(a, b)
    if overlap:
        tail = b.split()
        return (a + " " + " ".join(tail[overlap:])).strip()
    if _similar(a, b) >= 0.9:
        return a if len(a) >= len(b) else b
    folded_a, folded_b = fold_for_compare(a), fold_for_compare(b)
    if folded_b and folded_b in folded_a:
        return a
    if folded_a and folded_a in folded_b:
        return b
    return None


@dataclass
class PageResult:
    """One assembled page, ready for verification and output."""

    index: int
    label: str
    blocks: List[Block] = field(default_factory=list)
    page_number: Optional[str] = None
    agreement: float = 1.0
    legibility: str = "high"
    notes: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)
    ignored_overlays: List[str] = field(default_factory=list)
    corrections: List[dict] = field(default_factory=list)
    confidence: float = 1.0
    usage: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks if block.text.strip())


def merge_tiles(tile_blocks: Sequence[Sequence[Block]], join_cut_paragraphs: bool = True) -> List[Block]:
    """Concatenate per-tile blocks, removing the deliberate overlap."""
    merged: List[Block] = []
    for blocks in tile_blocks:
        blocks = [b for b in blocks if b.text.strip()]
        if not merged:
            merged.extend(Block(b.type, b.text.strip()) for b in blocks)
            continue

        remaining = list(blocks)

        # 1. Drop whole blocks the previous tile already produced.
        while remaining and any(
            _similar(remaining[0].text, previous.text) >= 0.92 for previous in merged[-4:]
        ):
            remaining.pop(0)

        # 2. Splice a paragraph that the tile boundary cut in half.
        if remaining and merged:
            joined = splice(merged[-1].text, remaining[0].text)
            if joined is not None:
                merged[-1] = Block(merged[-1].type, joined)
                remaining.pop(0)
            elif (
                join_cut_paragraphs
                and merged[-1].type == "paragraph"
                and remaining[0].type == "paragraph"
                and merged[-1].text
                and merged[-1].text[-1] not in SENTENCE_END
            ):
                merged[-1] = Block("paragraph", f"{merged[-1].text} {remaining[0].text}".strip())
                remaining.pop(0)

        merged.extend(Block(b.type, b.text.strip()) for b in remaining)
    return merged


def page_numbers_in(blocks: Sequence[Block]) -> List[str]:
    """Every page number printed on the page, in order.

    Usually one; two when the image spans a page break, which is the normal
    shape of a screenshot taken while scrolling.
    """
    return [b.text.strip() for b in blocks if b.type == "page_number" and b.text.strip()]


def _page_number_from_blocks(blocks: Sequence[Block]) -> Optional[str]:
    numbers = page_numbers_in(blocks)
    return numbers[0] if numbers else None


def render_document(
    pages: Sequence[PageResult],
    *,
    page_marks: str = "number",
    join_pages: bool = True,
    keep_footnotes: bool = True,
    page_separator: str = "\n\n",
) -> str:
    """Turn assembled pages into the final plain-text document.

    Printed page numbers stay where the page printed them. That matters for
    the common case of a screenshot or scan that spans a page break and so
    carries two of them: the number closing the previous page and the number
    closing this one. Hoisting them to a fixed position would silently drop
    one of the two and put the other in the wrong place.
    """
    chunks: List[str] = []
    for page in pages:
        body: List[str] = []
        footnotes: List[str] = []
        for block in page.blocks:
            text = block.text.strip()
            if not text:
                continue
            if block.type == "page_number":
                if page_marks == "none":
                    continue
                body.append(text if page_marks == "number" else f"[صفحهٔ {text}]")
            elif block.type == "footnote":
                footnotes.append(text)
            else:
                body.append(text)

        page.page_number = page.page_number or _page_number_from_blocks(page.blocks)

        if keep_footnotes and footnotes:
            body.append("\n".join(footnotes))

        page_text = "\n\n".join(body).strip()
        if not page_text:
            continue

        if (
            join_pages
            and chunks
            and page_marks == "none"
            and chunks[-1]
            and chunks[-1].rstrip()[-1:] not in SENTENCE_END
        ):
            # A paragraph that ran over the page break: rejoin the halves.
            head, _, tail = chunks[-1].rpartition("\n\n")
            first, _, rest = page_text.partition("\n\n")
            joined = f"{tail.strip()} {first.strip()}".strip()
            chunks[-1] = f"{head}\n\n{joined}".strip() if head else joined
            if rest.strip():
                chunks.append(rest.strip())
            continue

        chunks.append(page_text)

    return page_separator.join(chunks).strip() + "\n"


def paragraph_stats(text: str) -> dict:
    words = re.findall(r"\S+", text)
    return {
        "characters": len(text),
        "words": len(words),
        "paragraphs": len([p for p in text.split("\n\n") if p.strip()]),
        "lines": len([l for l in text.split("\n") if l.strip()]),
    }
