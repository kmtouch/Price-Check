"""Reconcile several independent readings of the same image.

Running the OCR twice with different framings and comparing the results is the
cheapest reliable confidence signal there is: characters both passes agree on
are almost always right, and the handful they disagree about is exactly the
list the verifier should re-read against the image.
"""

from __future__ import annotations

import difflib
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .engines.base import Block, PageReading
from .normalize import fold_for_compare


@dataclass
class Disagreement:
    """A span where the passes did not read the same thing."""

    block_index: int
    variants: List[str]
    chosen: str

    def describe(self) -> str:
        others = " | ".join(v if v else "∅" for v in self.variants if v != self.chosen)
        return f"passes disagree: “{self.chosen or '∅'}” vs “{others}”"


@dataclass
class ConsensusResult:
    blocks: List[Block]
    disagreements: List[Disagreement] = field(default_factory=list)
    agreement: float = 1.0
    structure_mismatch: bool = False
    page_number: Optional[str] = None
    ignored_overlays: List[str] = field(default_factory=list)
    uncertain_spans: List[dict] = field(default_factory=list)
    legibility: str = "high"

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks if block.text.strip())


def _tokens(text: str) -> List[str]:
    return text.split()


def _merge_spans(spans: List[Tuple[int, int, List[str]]]) -> List[Tuple[int, int, List[List[str]]]]:
    """Group per-pass edit spans that cover the same region of the base text."""
    spans = sorted(spans, key=lambda s: (s[0], s[1]))
    merged: List[Tuple[int, int, List[List[str]]]] = []
    for start, end, replacement in spans:
        if merged and start <= merged[-1][1]:
            prev_start, prev_end, variants = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end), variants + [replacement])
        else:
            merged.append((start, end, [replacement]))
    return merged


def vote_tokens(sequences: Sequence[List[str]]) -> Tuple[List[str], List[List[str]]]:
    """Merge word sequences by majority vote, reporting contested spans.

    The first sequence is the reference frame; every other sequence is diffed
    against it and its edits are collected per region. A region where more
    passes propose the same replacement than keep the reference wins; ties keep
    the reference, which is the pass run without any special framing.
    """
    if not sequences:
        return [], []
    base = list(sequences[0])
    if len(sequences) == 1:
        return base, []

    spans: List[Tuple[int, int, List[str]]] = []
    for other in sequences[1:]:
        matcher = difflib.SequenceMatcher(None, base, other, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "equal":
                spans.append((i1, i2, list(other[j1:j2])))

    contested: List[List[str]] = []
    result: List[str] = []
    cursor = 0
    for start, end, variants in _merge_spans(spans):
        result.extend(base[cursor:start])
        options = Counter()
        reference = tuple(base[start:end])
        options[reference] += 1
        for variant in variants:
            options[tuple(variant)] += 1
        # Passes that produced no edit here implicitly voted for the reference.
        options[reference] += (len(sequences) - 1) - len(variants)

        best, best_count = reference, options[reference]
        for option, count in options.items():
            if count > best_count:
                best, best_count = option, count
        result.extend(best)
        if len(options) > 1:
            contested.append([" ".join(option) for option in options])
        cursor = end
    result.extend(base[cursor:])
    return result, contested


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, fold_for_compare(a), fold_for_compare(b), autojunk=False).ratio()


def _pick_base(readings: Sequence[PageReading]) -> int:
    """Index of the reading most similar to all the others (the medoid)."""
    best_index, best_score = 0, -1.0
    for i, reading in enumerate(readings):
        score = sum(_similarity(reading.text, other.text) for j, other in enumerate(readings) if i != j)
        if score > best_score:
            best_index, best_score = i, score
    return best_index


def reconcile(readings: Sequence[PageReading]) -> ConsensusResult:
    """Combine N readings of one tile into a single best-effort reading."""
    readings = [r for r in readings if r is not None]
    if not readings:
        return ConsensusResult(blocks=[])
    if len(readings) == 1:
        only = readings[0]
        return ConsensusResult(
            blocks=list(only.blocks),
            agreement=1.0,
            page_number=only.page_number,
            ignored_overlays=list(only.ignored_overlays),
            uncertain_spans=list(only.uncertain_spans),
            legibility=only.legibility,
        )

    base_index = _pick_base(readings)
    base = readings[base_index]
    others = [r for i, r in enumerate(readings) if i != base_index]

    overlays = list(dict.fromkeys(o for r in readings for o in r.ignored_overlays))
    uncertain = [span for r in readings for span in r.uncertain_spans]
    legibility = min((r.legibility for r in readings), key=lambda x: ["high", "medium", "low"].index(x))
    page_number = next((r.page_number for r in readings if r.page_number), None)

    structure_mismatch = any(len(r.blocks) != len(base.blocks) for r in others)
    disagreements: List[Disagreement] = []

    if structure_mismatch:
        # Block boundaries differ, so merging block-by-block would misalign the
        # text. Fall back to the medoid reading and say so loudly.
        agreement = sum(_similarity(base.text, other.text) for other in others) / len(others)
        return ConsensusResult(
            blocks=list(base.blocks),
            disagreements=[],
            agreement=agreement,
            structure_mismatch=True,
            page_number=page_number,
            ignored_overlays=overlays,
            uncertain_spans=uncertain,
            legibility=legibility,
        )

    merged_blocks: List[Block] = []
    total_tokens = 0
    contested_tokens = 0
    for index, block in enumerate(base.blocks):
        sequences = [_tokens(block.text)] + [_tokens(r.blocks[index].text) for r in others]
        merged, contested = vote_tokens(sequences)
        merged_blocks.append(Block(block.type, " ".join(merged)))
        total_tokens += max(len(sequence) for sequence in sequences) or 1
        for options in contested:
            contested_tokens += max(len(option.split()) for option in options)
            chosen = options[0]
            disagreements.append(Disagreement(index, options, chosen))

    agreement = 1.0 - (contested_tokens / total_tokens if total_tokens else 0.0)
    # Report the chosen variant rather than the first option offered.
    for disagreement in disagreements:
        block_text = merged_blocks[disagreement.block_index].text
        for variant in disagreement.variants:
            if variant and variant in block_text:
                disagreement.chosen = variant
                break

    return ConsensusResult(
        blocks=merged_blocks,
        disagreements=disagreements,
        agreement=max(0.0, min(1.0, agreement)),
        page_number=page_number,
        ignored_overlays=overlays,
        uncertain_spans=uncertain,
        legibility=legibility,
    )
