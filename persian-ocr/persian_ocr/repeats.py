"""Detect and strip running headers, footers, and leaked watermark text.

The OCR prompt already tells the model to keep watermark/UI text out of the
transcription entirely (see ``OCR_SYSTEM`` rule 4), so this is the safety net
for what gets through anyway, plus the case the prompt does not try to
handle at all: a *genuine* printed running header or footer — a book title
repeated at the top of every page, a publisher line at the bottom, a page
banner that only differs by its page number. Those are real printed content,
not noise, so removing them is a choice the caller makes explicitly.

The signal used is repetition, not appearance: a line that shows up as the
first or last block of a page, worded identically (ignoring digits — a page
number embedded in the line must not defeat the match) on enough other
pages, is almost certainly boundary matter rather than body text. A real
paragraph that happens to open two pages with the same sentence is exactly
the kind of thing this must not delete, which is why the bar is "enough
pages", not "more than one".
"""

from __future__ import annotations

import math
import re
from typing import List, Sequence, Set

from .engines.base import Block
from .normalize import fold_for_compare

_DIGIT_RUN_RE = re.compile(r"[0-9۰-۹]+")


def _signature(text: str) -> str:
    """Fold the text for comparison and collapse any digit run to one marker.

    Collapsing digits is what lets "صفحه‌ی ۱۲" and "صفحه‌ی ۱۳" register as the
    same running footer instead of two unrelated one-off lines.
    """
    folded = fold_for_compare(text)
    return _DIGIT_RUN_RE.sub("#", folded)


def detect_repeated_boundaries(
    pages: Sequence[Sequence[Block]],
    *,
    min_occurrences: int = 3,
    min_fraction: float = 0.3,
) -> Set[str]:
    """Signatures of lines that recur as a page's first or last block often
    enough to be a running header/footer/watermark rather than body text.

    Needs both an absolute floor (``min_occurrences``) and a share of the
    document (``min_fraction``) — the floor keeps a short document from
    flagging something after two coincidental repeats, the share keeps a long
    document from needing dozens of repeats before it notices a pattern that
    is already obvious after the first handful of pages.
    """
    counts: dict = {}
    total = 0
    for blocks in pages:
        visible = [b for b in blocks if b.text.strip()]
        if not visible:
            continue
        total += 1
        candidates = {visible[0].text}
        if len(visible) > 1:
            candidates.add(visible[-1].text)
        for text in candidates:
            signature = _signature(text)
            if len(signature) < 3:
                continue  # too short to mean anything (a lone page number, say)
            counts[signature] = counts.get(signature, 0) + 1

    threshold = max(min_occurrences, math.ceil(min_fraction * total))
    return {signature for signature, count in counts.items() if count >= threshold}


def strip_repeated_boundaries(pages: Sequence[Sequence[Block]], signatures: Set[str]) -> List[List[Block]]:
    """Drop boundary blocks matching `signatures`; leave everything else untouched."""
    if not signatures:
        return [list(blocks) for blocks in pages]

    cleaned: List[List[Block]] = []
    for blocks in pages:
        visible_indices = [i for i, b in enumerate(blocks) if b.text.strip()]
        boundary_indices = set()
        if visible_indices:
            boundary_indices.add(visible_indices[0])
            if len(visible_indices) > 1:
                boundary_indices.add(visible_indices[-1])

        kept = [
            block
            for i, block in enumerate(blocks)
            if not (i in boundary_indices and _signature(block.text) in signatures)
        ]
        cleaned.append(kept)
    return cleaned
