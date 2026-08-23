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
from typing import List, Optional, Sequence, Tuple

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


#: How much of a block has to be accounted for by its neighbour before we call
#: it the same text. Two readings of the same lines are never byte-identical —
#: a colon or a half-space differs — so this is deliberately not 1.0.
CONTAINMENT = 0.85


def relate(existing: str, candidate: str) -> Tuple[str, Optional[str]]:
    """Decide how a block from the next tile relates to one already merged.

    Tiles overlap on purpose, so the next tile usually re-reads lines that are
    already in the document — sometimes as a whole repeated paragraph,
    sometimes as the tail of a paragraph that was cut, sometimes as the
    *complete* version of a paragraph the previous tile only saw the top of.
    All three have to be recognised, or the page comes out doubled.

    Returns one of:
      ``("duplicate", None)``   — the candidate adds nothing, drop it
      ``("fuller", text)``      — the candidate is the more complete reading
      ``("continues", text)``   — the two halves join into one paragraph
      ``("unrelated", None)``   — genuinely new text
    """
    a, b = _folded_words(existing), _folded_words(candidate)
    if not a or not b:
        return ("unrelated", None)

    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    blocks = [m for m in matcher.get_matching_blocks() if m.size]
    if not blocks:
        return ("unrelated", None)
    # Total matched words, not the longest single run: two readings of the same
    # lines differ in small ways (a colon, a half-space) that split one long
    # match into several, and judging by the longest run alone then misses the
    # repeat by a hair.
    matched = sum(m.size for m in blocks)
    longest = max(blocks, key=lambda m: m.size)

    # Unrelated Persian paragraphs still share function words, so a high total
    # only counts when at least one substantial run backs it up.
    substantial = longest.size >= max(MIN_OVERLAP_WORDS, 0.35 * min(len(a), len(b)))

    if substantial and matched >= CONTAINMENT * len(b):
        return ("duplicate", None)
    if substantial and matched >= CONTAINMENT * len(a):
        return ("fuller", candidate)
    # The tail of what we have is the head of what arrived: one paragraph, cut.
    if (
        longest.size >= MIN_OVERLAP_WORDS
        and longest.a + longest.size >= len(a) - 1
        and longest.b <= 1
    ):
        tail = candidate.split()[longest.b + longest.size :]
        return ("continues", (existing + " " + " ".join(tail)).strip())
    return ("unrelated", None)


def splice(a: str, b: str) -> Optional[str]:
    """Join two halves of the same paragraph read from overlapping tiles."""
    kind, text = relate(a, b)
    if kind == "duplicate":
        return a
    if kind == "fuller":
        return text
    if kind == "continues":
        return text
    overlap = find_overlap(a, b)
    if overlap:
        return (a + " " + " ".join(b.split()[overlap:])).strip()
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


#: How far back to look for a block the new tile is repeating. Generous
#: overlaps can repeat several paragraphs, not just the seam.
LOOKBACK_BLOCKS = 8


def merge_tiles(tile_blocks: Sequence[Sequence[Block]], join_cut_paragraphs: bool = True) -> List[Block]:
    """Concatenate per-tile blocks, removing the deliberate overlap.

    Each block of an arriving tile is checked against the last few blocks
    already merged, because a 50%-overlapping tile repeats whole paragraphs
    rather than just clipping one at the seam.
    """
    merged: List[Block] = []
    for tile_index, blocks in enumerate(tile_blocks):
        blocks = [Block(b.type, b.text.strip()) for b in blocks if b.text.strip()]
        if not merged:
            merged.extend(blocks)
            continue

        first_of_tile = True
        for block in blocks:
            placed = False
            start = max(0, len(merged) - LOOKBACK_BLOCKS)
            for position in range(len(merged) - 1, start - 1, -1):
                kind, text = relate(merged[position].text, block.text)
                if kind == "duplicate":
                    placed = True
                    break
                if kind == "fuller":
                    merged[position] = Block(merged[position].type, text)
                    placed = True
                    break
                if kind == "continues" and position == len(merged) - 1:
                    merged[position] = Block(merged[position].type, text)
                    placed = True
                    break
            if placed:
                first_of_tile = False
                continue

            # No textual overlap at all: only the very first block of a tile can
            # be the continuation of a paragraph the previous tile cut off.
            if (
                join_cut_paragraphs
                and first_of_tile
                and merged
                and merged[-1].type == "paragraph"
                and block.type == "paragraph"
                and merged[-1].text
                and merged[-1].text[-1] not in SENTENCE_END
            ):
                merged[-1] = Block("paragraph", f"{merged[-1].text} {block.text}".strip())
            else:
                merged.append(block)
            first_of_tile = False

    return _drop_repeats(merged)


def _drop_repeats(blocks: List[Block]) -> List[Block]:
    """Final safety net: no block may repeat an earlier one on the same page."""
    kept: List[Block] = []
    for block in blocks:
        if any(relate(earlier.text, block.text)[0] == "duplicate" for earlier in kept):
            continue
        kept.append(block)
    return kept


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
