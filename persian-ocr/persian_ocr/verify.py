"""Automatic verification.

The pipeline never trusts a single reading. Every page goes through four
independent checks, and only then is a correction allowed to touch the text:

1. **Cross-pass consensus** — where two independent readings disagree.
2. **Structural rules** — unbalanced « », stray application chrome, repeated
   words, orphan footnote markers, mixed digit families.
3. **Vocabulary screening** — words that neither the reference list nor the
   document itself can account for.
4. **Re-reading against the image** — the flagged spans (and the page as a
   whole) are shown to the model together with the image, and it reports what
   the page actually says.

Corrections coming back from step 4 are *not* applied blindly. A correction has
to name a span that really exists in the text, be confident enough, and stay
close enough to the original that it is plainly a fix rather than a rewrite.
Everything rejected is recorded in the report instead of being silently
dropped.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .engines.base import Block
from .lexicon import Lexicon
from .normalize import fold_for_compare

# Text that belongs to a PDF reader or a phone, never to a book page.
UI_CHROME_PATTERNS = [
    r"\bEdit\s*PDF\b", r"\bFill\s*&\s*Sign\b", r"\bMore\s*tools\b", r"\bHighlight\b",
    r"\bComment\b", r"\bContinue\b", r"\bGenerative\s+summary\b", r"\bAI\s+User\s+Guidelines\b",
    r"\bDraw\b", r"\bShare\b", r"\bSearch\b", r"\bBookmark\b", r"\bPage\s+\d+\s+of\s+\d+\b",
    r"\bScanned\s+by\b", r"\bCamScanner\b", r"\bDownload\b", r"\bSign\s*in\b",
]

FOOTNOTE_MARKER_RE = re.compile(r"\(\s*([۰-۹0-9]{1,3})\s*\)")
PERSIAN_DIGIT_RE = re.compile(r"[۰-۹]")
LATIN_DIGIT_RE = re.compile(r"(?<![A-Za-z0-9])[0-9]+(?![A-Za-z0-9])")


@dataclass
class Correction:
    block_index: int
    original: str
    corrected: str
    reason: str
    confidence: float
    applied: bool = False
    rejected_because: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "block_index": self.block_index,
            "original": self.original,
            "corrected": self.corrected,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "applied": self.applied,
            "rejected_because": self.rejected_because,
        }


@dataclass
class CheckReport:
    flags: List[str] = field(default_factory=list)
    structural: List[str] = field(default_factory=list)
    vocabulary: List[str] = field(default_factory=list)
    consensus: List[str] = field(default_factory=list)
    lexicon_coverage: float = 1.0

    def all_flags(self) -> List[str]:
        return self.consensus + self.structural + self.vocabulary


def check_structure(blocks: Sequence[Block]) -> List[str]:
    """Rule-based sanity checks that need no model call."""
    problems: List[str] = []
    text = "\n".join(block.text for block in blocks)

    opens, closes = text.count("«"), text.count("»")
    if opens != closes:
        problems.append(f"unbalanced guillemets: {opens} × « and {closes} × »")
    for left, right, name in (("(", ")", "parentheses"), ("[", "]", "brackets")):
        if text.count(left) != text.count(right):
            problems.append(f"unbalanced {name}: {text.count(left)} × {left}, {text.count(right)} × {right}")

    for pattern in UI_CHROME_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            problems.append(f"application chrome leaked into the text: “{match.group(0)}”")

    if PERSIAN_DIGIT_RE.search(text) and LATIN_DIGIT_RE.search(text):
        sample = LATIN_DIGIT_RE.search(text).group(0)
        problems.append(f"mixed digit families: Persian digits alongside “{sample}”")

    for match in re.finditer(r"(\b[^\W\d_]{2,}\b)\s+\1\b", text, re.UNICODE):
        problems.append(f"word printed twice in a row: “{match.group(1)}”")

    for index, block in enumerate(blocks):
        if block.type == "paragraph" and len(block.text.strip()) < 2:
            problems.append(f"block {index} is empty")
        if "⟨؟⟩" in block.text:
            problems.append(f"block {index} contains an unreadable span (⟨؟⟩)")
        if re.search(r"[A-Za-z]{3,}", block.text) and not re.search(r"[À-ɏ]", block.text):
            latin = re.findall(r"[A-Za-z]{3,}", block.text)
            if len(" ".join(latin)) > 40:
                problems.append(f"block {index} holds a lot of Latin text: “{' '.join(latin)[:60]}”")

    markers = [int(m.group(1).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
               for m in FOOTNOTE_MARKER_RE.finditer(text)]
    if markers and markers != sorted(markers):
        problems.append(f"footnote markers are out of order: {markers}")

    return problems


def run_checks(blocks: Sequence[Block], lexicon: Lexicon, consensus_flags: Sequence[str] = ()) -> CheckReport:
    text = "\n".join(block.text for block in blocks)
    report = CheckReport()
    report.consensus = list(consensus_flags)
    report.structural = check_structure(blocks)
    report.vocabulary = [flag.describe() for flag in lexicon.screen(text)]
    report.lexicon_coverage = lexicon.coverage(text)
    report.flags = report.all_flags()
    return report


# -- applying corrections -------------------------------------------------
def _drift(original: str, corrected: str) -> float:
    """0.0 = identical, 1.0 = unrecognisably different."""
    if not original and not corrected:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(
        None, fold_for_compare(original), fold_for_compare(corrected), autojunk=False
    ).ratio()


def changed_words(original: str, corrected: str) -> int:
    """How many whole words a correction touches.

    This is the signal that separates a reading fix from a rewrite. Fixing a
    misread letter changes characters *inside* one or two words; swapping
    واژه‌ها for واژگان and عبارت‌ها for عبارات is a different kind of edit
    entirely — it substitutes lexical items, which is editing the book, not
    transcribing it. Character-level similarity cannot tell the two apart,
    because Persian synonyms share their stems.
    """
    before = fold_for_compare(original).split()
    after = fold_for_compare(corrected).split()
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )


def vet_correction(
    correction: Correction,
    blocks: Sequence[Block],
    *,
    min_confidence: float,
    max_drift: float,
    max_changed_words: int = 2,
) -> Optional[str]:
    """Return the reason to reject a correction, or None to accept it."""
    if correction.confidence < min_confidence:
        return f"confidence {correction.confidence:.2f} below the {min_confidence:.2f} threshold"
    if not correction.original:
        return "no original span given"
    if not 0 <= correction.block_index < len(blocks):
        return f"block {correction.block_index} does not exist"
    if correction.original not in blocks[correction.block_index].text:
        return "the quoted original does not appear in that block"
    if correction.original == correction.corrected:
        return "no change proposed"
    if len(correction.original) > 400:
        return "span too large to be a targeted fix"

    is_overlay_removal = correction.corrected.strip() == ""
    if is_overlay_removal:
        # Deleting text is only allowed for application chrome, and only in
        # small amounts — never a whole paragraph of the book.
        if len(correction.original) > 120:
            return "refusing to delete a large span"
        if not re.search(r"[A-Za-z]", correction.original) and "overlay" not in correction.reason.lower():
            return "deletion is only allowed for overlay text"
        return None

    drift = _drift(correction.original, correction.corrected)
    if drift == 0.0:
        # The two forms are the same text differently encoded (half-space,
        # digit family, Arabic look-alike): a spelling fix, whatever its size.
        return None
    touched = changed_words(correction.original, correction.corrected)
    if touched > max_changed_words:
        return (
            f"changes {touched} whole words — that is a rewrite, not a targeted fix"
        )
    if drift > max_drift and len(correction.original) > 12:
        return f"rewrites too much of the span (drift {drift:.2f} > {max_drift:.2f})"
    length_ratio = len(correction.corrected) / max(1, len(correction.original))
    if length_ratio > 2.5 or length_ratio < 0.35:
        return f"length changes too much ({len(correction.original)} → {len(correction.corrected)} chars)"
    return None


def apply_corrections(
    blocks: List[Block],
    corrections: Sequence[Correction],
    *,
    min_confidence: float = 0.75,
    max_drift: float = 0.4,
    max_changed_words: int = 2,
    already_applied: Sequence[Tuple[str, str]] = (),
) -> Tuple[List[Block], List[Correction]]:
    """Apply the corrections that survive vetting; record why the rest did not.

    `already_applied` lists (original, corrected) pairs from earlier rounds, so
    a re-proposed fix is dropped quietly instead of being logged as a rejection
    for a span that no longer exists.
    """
    updated = [Block(block.type, block.text) for block in blocks]
    processed: List[Correction] = []
    seen = {(original, corrected) for original, corrected in already_applied}
    for correction in corrections:
        if (correction.original, correction.corrected) in seen:
            continue
        reason = vet_correction(
            correction, updated, min_confidence=min_confidence, max_drift=max_drift,
            max_changed_words=max_changed_words,
        )
        if reason is not None:
            correction.rejected_because = reason
            processed.append(correction)
            continue
        block = updated[correction.block_index]
        replaced = block.text.replace(correction.original, correction.corrected, 1)
        updated[correction.block_index] = Block(block.type, re.sub(r"\s{2,}", " ", replaced).strip())
        correction.applied = True
        processed.append(correction)
    return updated, processed


def parse_corrections(payload: Dict) -> List[Correction]:
    corrections: List[Correction] = []
    for item in payload.get("corrections", []) or []:
        try:
            corrections.append(
                Correction(
                    block_index=int(item.get("block_index", -1)),
                    original=str(item.get("original", "")),
                    corrected=str(item.get("corrected", "")),
                    reason=str(item.get("reason", "")),
                    confidence=float(item.get("confidence", 0.0)),
                )
            )
        except (TypeError, ValueError):
            continue
    return corrections


def apply_missing_text(blocks: List[Block], payload: Dict, min_confidence: float) -> Tuple[List[Block], List[str]]:
    """Insert text the verifier says the transcription dropped entirely."""
    notes: List[str] = []
    additions = payload.get("missing_text", []) or []
    for item in sorted(additions, key=lambda i: -int(i.get("after_block_index", 0) or 0)):
        text = str(item.get("text", "")).strip()
        try:
            confidence = float(item.get("confidence", 0.0))
            position = int(item.get("after_block_index", -1))
        except (TypeError, ValueError):
            continue
        if not text or confidence < min_confidence:
            continue
        if any(fold_for_compare(text) in fold_for_compare(block.text) for block in blocks):
            continue  # already there
        position = max(-1, min(position, len(blocks) - 1))
        blocks.insert(position + 1, Block("paragraph", text))
        notes.append(f"inserted missing text after block {position}: “{text[:60]}”")
    return blocks, notes


def confidence_score(
    *,
    agreement: float,
    lexicon_coverage: float,
    structural_problems: int,
    unresolved_flags: int,
    words: int,
    legibility: str = "high",
) -> float:
    """A single 0-1 number summarising how much to trust a page.

    Cross-pass agreement carries most of the weight because it is the signal
    that most directly measures reading risk. Vocabulary coverage is scored
    against a realistic target rather than perfection — even a good run over
    literary Persian leaves a few rare compounds unaccounted for — and the flag
    penalty is proportional to page length, so a long page is not punished
    simply for containing more words.
    """
    legibility_factor = {"high": 1.0, "medium": 0.94, "low": 0.85}.get(legibility, 1.0)
    coverage_score = min(1.0, lexicon_coverage / 0.95)
    base = 0.65 * agreement + 0.35 * coverage_score
    penalty = 0.03 * structural_problems + min(0.15, 0.5 * unresolved_flags / max(words, 20))
    if words < 10:
        base *= 0.9
    return max(0.0, min(1.0, (base - penalty) * legibility_factor))
