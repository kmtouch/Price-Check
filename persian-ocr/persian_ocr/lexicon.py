"""Vocabulary screening for Persian text.

The goal is *not* to spell-check Persian — no bundled list can, and blindly
"fixing" a rare literary word would be worse than leaving an OCR slip in. The
goal is to decide **where to look again**: words this module cannot account for
are handed to the verifier, which re-reads them against the page image.

Three sources of evidence, cheapest first:

1. shape rules — sequences that simply cannot occur in Persian orthography;
2. the document's own vocabulary — a word printed several times across a book
   is almost certainly a real word, even if no list contains it;
3. a bundled high-frequency list plus optional user dictionaries, matched
   through prefix/suffix stripping so inflected forms resolve to their stem.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

from .normalize import HARAKAT, PERSIAN_LETTERS, ZWNJ

DATA_DIR = Path(__file__).parent / "data"

WORD_RE = re.compile(rf"[{PERSIAN_LETTERS}{HARAKAT}{ZWNJ}]+")
#: Tokeniser used for screening: it deliberately swallows adjacent Latin
#: letters so that a Latin/Persian hybrid (a classic OCR artefact) shows up as
#: one broken token instead of one clean Persian token.
TOKEN_RE = re.compile(rf"[{PERSIAN_LETTERS}{HARAKAT}{ZWNJ}A-Za-zÀ-ɏ]+")
LATIN_RE = re.compile(r"[A-Za-zÀ-ɏ]")
PERSIAN_RE = re.compile(rf"[{PERSIAN_LETTERS}]")

PREFIXES = ("نمی", "می", "بی", "با", "بر", "در", "هم", "نا", "پر", "ب", "ن")
#: Ordered longest-first: plural and possessive endings, then the personal
#: verb endings, then the bare ones. Stripping these lets a stem in the word
#: list account for the inflected forms a book actually prints.
SUFFIXES = (
    "هایی", "هایم", "هایت", "هایش", "هایمان", "هایتان", "هایشان",
    "های", "ها", "ترین", "تر", "مان", "تان", "شان",
    "ام", "ات", "اش", "ای", "اید", "اند", "ایم",
    "یم", "ید", "ند", "یی", "گان", "یان", "ان", "ی", "م", "د", "ه", "ست",
)

#: Letters that never begin a Persian word.
NEVER_INITIAL = set("ةًٌٍَُِّْ")
#: Character pairs that do not occur in well-formed Persian words.
IMPOSSIBLE_PAIRS = {"ءء", "ااا", "ییی", "ههه", "ننن", "ررر", "ووو"}


@dataclass
class Flag:
    """One suspicious span, to be checked against the image."""

    word: str
    reason: str
    count: int = 1

    def describe(self) -> str:
        suffix = f" (×{self.count})" if self.count > 1 else ""
        return f"{self.word} — {self.reason}{suffix}"


def fold_word(word: str) -> str:
    """Reduce a word to the form used for dictionary lookups."""
    word = unicodedata.normalize("NFC", word)
    word = re.sub(rf"[{HARAKAT}ـ{ZWNJ}]", "", word)
    return (
        word.replace("ي", "ی").replace("ك", "ک").replace("ى", "ی")
        .replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")
    )


def load_wordlist(path: Path) -> Set[str]:
    words: Set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Hunspell .dic entries look like `word/AFFIXFLAGS`.
        line = line.split("/")[0].strip()
        if line:
            words.add(fold_word(line))
    return words


class Lexicon:
    """Decides whether a word is accounted for, and why not when it is not."""

    def __init__(
        self,
        extra_paths: Sequence[Path] = (),
        document_text: str = "",
        document_min_count: int = 2,
        builtin: bool = True,
    ):
        self.words: Set[str] = set()
        if builtin:
            builtin_path = DATA_DIR / "common_fa.txt"
            if builtin_path.exists():
                self.words |= load_wordlist(builtin_path)
        for path in extra_paths:
            path = Path(path)
            if not path.exists():
                raise FileNotFoundError(f"dictionary not found: {path}")
            self.words |= load_wordlist(path)

        self.document_words: Set[str] = set()
        if document_text:
            counts = Counter(fold_word(word) for word in WORD_RE.findall(document_text))
            self.document_words = {
                word for word, count in counts.items() if count >= document_min_count
            }

    # -- membership --------------------------------------------------------
    def _known_form(self, folded: str) -> bool:
        return folded in self.words or folded in self.document_words

    def known(self, word: str) -> bool:
        """True when the word, or a plausible stem of it, is accounted for."""
        folded = fold_word(word)
        if len(folded) <= 1 or folded.isdigit():
            return True
        if self._known_form(folded):
            return True
        for suffix in SUFFIXES:
            if folded.endswith(suffix) and len(folded) - len(suffix) >= 2:
                stem = folded[: -len(suffix)]
                if self._known_form(stem) or self._known_form(stem + "ه"):
                    return True
        for prefix in PREFIXES:
            if folded.startswith(prefix) and len(folded) - len(prefix) >= 2:
                stem = folded[len(prefix) :]
                if self._known_form(stem):
                    return True
                for suffix in SUFFIXES:
                    if stem.endswith(suffix) and len(stem) - len(suffix) >= 2:
                        if self._known_form(stem[: -len(suffix)]):
                            return True
        return False

    # -- shape rules -------------------------------------------------------
    @staticmethod
    def shape_problem(word: str) -> Optional[str]:
        """Report a structural impossibility, if the word has one."""
        if LATIN_RE.search(word) and PERSIAN_RE.search(word):
            return "Persian and Latin letters mixed inside one word"
        stripped = re.sub(rf"[{HARAKAT}{ZWNJ}]", "", word)
        if not stripped:
            return "only diacritics, no letters"
        leading = word.lstrip(ZWNJ)
        if leading and leading[0] in NEVER_INITIAL:
            return f"word cannot start with {leading[0]!r}"
        for pair in IMPOSSIBLE_PAIRS:
            if pair in stripped:
                return f"impossible letter sequence {pair!r}"
        if re.search(rf"[{HARAKAT}]{{3,}}", word):
            return "three or more stacked diacritics"
        if len(stripped) > 22:
            return "implausibly long word (probably two words run together)"
        return None

    # -- the interesting bit ----------------------------------------------
    def screen(self, text: str, max_flags: int = 40) -> List[Flag]:
        """Return the spans worth re-reading, most frequent first."""
        counts: Counter = Counter()
        reasons = {}
        for word in TOKEN_RE.findall(text):
            if not PERSIAN_RE.search(word):
                continue  # a foreign-script word, transcribed as printed
            if len(fold_word(word)) < 2:
                continue
            problem = self.shape_problem(word)
            if problem is None and self.known(word):
                continue
            counts[word] += 1
            reasons[word] = problem or "not found in the reference vocabulary"

        flags = [Flag(word, reasons[word], count) for word, count in counts.items()]
        # A misreading usually appears once; a rare-but-real word repeats. Sort
        # single occurrences first so the verifier's attention goes there.
        flags.sort(key=lambda flag: (flag.count, -len(flag.word)))
        return flags[:max_flags]

    def coverage(self, text: str) -> float:
        """Fraction of word tokens the lexicon accounts for (0.0-1.0)."""
        words = [w for w in WORD_RE.findall(text) if len(fold_word(w)) >= 2]
        if not words:
            return 1.0
        return sum(1 for word in words if self.known(word)) / len(words)


def build_lexicon(extra_paths: Iterable[Path] = (), document_text: str = "") -> Lexicon:
    return Lexicon(tuple(extra_paths), document_text=document_text)
