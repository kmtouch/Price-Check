"""Accuracy metrics for benchmarking a run against a reference transcription."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from .normalize import fold_for_compare


def levenshtein(a: Sequence, b: Sequence) -> int:
    """Edit distance with O(min(len)) memory."""
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, item_a in enumerate(a, start=1):
        current = [i]
        for j, item_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,          # deletion
                    current[j - 1] + 1,       # insertion
                    previous[j - 1] + (item_a != item_b),  # substitution
                )
            )
        previous = current
    return previous[-1]


@dataclass
class Accuracy:
    cer: float
    wer: float
    reference_chars: int
    reference_words: int

    @property
    def character_accuracy(self) -> float:
        return max(0.0, 1.0 - self.cer)

    @property
    def word_accuracy(self) -> float:
        return max(0.0, 1.0 - self.wer)

    def to_dict(self) -> dict:
        return {
            "cer": round(self.cer, 5),
            "wer": round(self.wer, 5),
            "character_accuracy": round(self.character_accuracy, 5),
            "word_accuracy": round(self.word_accuracy, 5),
            "reference_chars": self.reference_chars,
            "reference_words": self.reference_words,
        }


def compare(hypothesis: str, reference: str, fold: bool = True) -> Accuracy:
    """Character- and word-error rates.

    With `fold=True` (the default) both sides are folded first, so differences
    that are encoding choices rather than reading errors — half-spaces, digit
    family, diacritics — do not count against the run. Pass `fold=False` for a
    strict, byte-level comparison.
    """
    hyp = fold_for_compare(hypothesis) if fold else hypothesis
    ref = fold_for_compare(reference) if fold else reference

    ref_chars = list(ref)
    ref_words = ref.split()
    cer = levenshtein(list(hyp), ref_chars) / max(1, len(ref_chars))
    wer = levenshtein(hyp.split(), ref_words) / max(1, len(ref_words))
    return Accuracy(cer=cer, wer=wer, reference_chars=len(ref_chars), reference_words=len(ref_words))


def diff_words(hypothesis: str, reference: str, limit: int = 40) -> List[str]:
    """Human-readable word-level differences, for the benchmark report."""
    import difflib

    hyp = fold_for_compare(hypothesis).split()
    ref = fold_for_compare(reference).split()
    out: List[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, hyp, ref, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        got = " ".join(hyp[i1:i2]) or "∅"
        want = " ".join(ref[j1:j2]) or "∅"
        out.append(f"{tag}: got “{got}” — reference “{want}”")
        if len(out) >= limit:
            break
    return out
