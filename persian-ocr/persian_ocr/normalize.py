"""Persian text normalisation.

Split deliberately into two tiers:

* **Encoding-level clean-up** (always safe, on by default) — Unicode form,
  invisible control characters, Arabic look-alike letters, digit families,
  punctuation spacing. None of this changes what the author wrote; it only
  fixes how it is encoded.
* **Orthographic normalisation** (``half_space="safe"``/``"aggressive"``) — the
  half-space (ZWNJ) decisions that Persian books genuinely disagree about.
  The default ``"safe"`` mode never imposes an outside style: it measures the
  document's *own* convention and only fixes places where the document
  contradicts itself, which is where OCR noise lives.

Tatweel (ـ) is preserved by default: in the kind of text this tool was built
for it is a deliberate authorial separator (برادرـ ام), not a stretching
artefact.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

ZWNJ = "‌"

# Characters that carry no meaning here and only break comparisons.
INVISIBLES = "​‍‎‏‪‫‬‭‮⁦⁧⁨⁩﻿­"

ARABIC_TO_PERSIAN = {
    "ي": "ی",  # ARABIC YEH        -> FARSI YEH
    "ى": "ی",  # ALEF MAKSURA      -> FARSI YEH
    "ې": "ی",  # E                 -> FARSI YEH
    "ك": "ک",  # ARABIC KAF        -> KEHEH
    "ڪ": "ک",  # SWASH KAF         -> KEHEH
    "ۀ": "هٔ",  # HEH WITH YEH ABOVE -> heh + hamza
    "ۍ": "ی",
    "ً": "ً",
}

TEH_MARBUTA = {"ة": "ه"}          # ة -> ه   (opt-in)
ARABIC_ALEFS = {"إ": "ا", "أ": "ا"}  # إ أ -> ا (opt-in)

ARABIC_INDIC_DIGITS = {chr(0x0660 + i): chr(0x06F0 + i) for i in range(10)}
LATIN_TO_PERSIAN_DIGITS = {str(i): chr(0x06F0 + i) for i in range(10)}
PERSIAN_TO_LATIN_DIGITS = {chr(0x06F0 + i): str(i) for i in range(10)}
ARABIC_INDIC_TO_LATIN = {chr(0x0660 + i): str(i) for i in range(10)}

PERSIAN_LETTERS = "ء-غـ-يٮ-ۓەۥۦۮۯۺ-ۿ"
HARAKAT = "ً-ْٰٓ-ٕٖ-ٟ"
PERSIAN_CHAR = f"[{PERSIAN_LETTERS}{HARAKAT}۰-۹]"
LATIN_CHAR = "[A-Za-zÀ-ɏ]"

# Punctuation that never takes a space before it and always one after.
CLOSE_PUNCT = "،؛؟!:.…"
OPEN_BRACKETS = "([{«"
CLOSE_BRACKETS = ")]}»"

_URL_RE = re.compile(r"(?:https?://|www\.)\S+|\S+@\S+\.\S+")


@dataclass
class NormalizeOptions:
    persian_digits: bool = True
    persian_punctuation: bool = True
    unify_arabic_letters: bool = True
    unify_teh_marbuta: bool = False
    unify_alef_hamza: bool = False
    strip_tatweel: bool = False
    smart_quotes: bool = True
    half_space: str = "safe"      # "off" | "safe" | "aggressive"
    fix_spacing: bool = True


class Normalizer:
    """Applies the rule chain and reports how often each rule fired."""

    def __init__(self, options: Optional[NormalizeOptions] = None):
        self.options = options or NormalizeOptions()

    # -- individual rules --------------------------------------------------
    @staticmethod
    def to_nfc(text: str) -> str:
        return unicodedata.normalize("NFC", text)

    @staticmethod
    def strip_invisibles(text: str) -> str:
        return text.translate({ord(ch): None for ch in INVISIBLES})

    @staticmethod
    def normalize_zwnj(text: str) -> str:
        """Resolve half-spaces that sit next to real whitespace.

        A ZWNJ touching a space is contradictory: one says "these are one
        word", the other says "these are two". Whitespace wins, always —
        gluing two genuinely separate words together is a corruption, whereas
        a dropped half-space is recoverable and gets restored later by
        `fix_half_spaces` if the document's own convention calls for it.
        """
        def resolve(match: re.Match) -> str:
            return "\n" if "\n" in match.group(0) else " "

        text = re.sub(rf"[ \t]*\n?[ \t]*{ZWNJ}+[ \t]*\n?[ \t]*", lambda m: (
            resolve(m) if re.search(r"[ \t\n]", m.group(0)) else ZWNJ
        ), text)
        text = re.sub(rf"{ZWNJ}{{2,}}", ZWNJ, text)
        text = re.sub(rf"(?m)^{ZWNJ}+|{ZWNJ}+$", "", text)
        return text

    def unify_letters(self, text: str) -> str:
        table = {}
        if self.options.unify_arabic_letters:
            table.update({ord(k): v for k, v in ARABIC_TO_PERSIAN.items()})
        if self.options.unify_teh_marbuta:
            table.update({ord(k): v for k, v in TEH_MARBUTA.items()})
        if self.options.unify_alef_hamza:
            table.update({ord(k): v for k, v in ARABIC_ALEFS.items()})
        if self.options.strip_tatweel:
            table[0x0640] = None
        return text.translate(table) if table else text

    def unify_digits(self, text: str) -> str:
        """Arabic-Indic digits always become Persian; Latin digits only in
        Persian context, so a German year or an ISBN keeps its own digits."""
        text = text.translate({ord(k): v for k, v in ARABIC_INDIC_DIGITS.items()})
        if not self.options.persian_digits:
            return text

        latin = re.compile(LATIN_CHAR)
        persian = re.compile(f"[{PERSIAN_LETTERS}]")
        persian_digits = str.maketrans(LATIN_TO_PERSIAN_DIGITS)

        def convert_line(line: str) -> str:
            if not persian.search(line):
                return line
            spans = []
            for match in _URL_RE.finditer(line):
                spans.append(match.span())

            def nearest_letter(index: int, step: int) -> str:
                while 0 <= index < len(line):
                    char = line[index]
                    if latin.match(char):
                        return "latin"
                    if persian.match(char):
                        return "persian"
                    if char == "\n":
                        break
                    index += step
                return ""

            def convert(match: re.Match) -> str:
                start, end = match.span()
                if any(s <= start < e for s, e in spans):
                    return match.group(0)
                if nearest_letter(start - 1, -1) == "latin":
                    return match.group(0)
                if nearest_letter(end, 1) == "latin":
                    return match.group(0)
                return match.group(0).translate(persian_digits)

            return re.sub(r"[0-9]+", convert, line)

        return "\n".join(convert_line(line) for line in text.split("\n"))

    #: Latin punctuation and its Persian counterpart.
    PUNCT_MAP = {",": "،", ";": "؛", "?": "؟"}

    def unify_punctuation(self, text: str) -> str:
        """Persianise , ; ? — but only inside Persian lines.

        Scholarly Persian quotes German, French and Latin inline; converting a
        comma inside "Also sprach Zarathustra, 1883" would be wrong. So the
        decision is made per line (is this a Persian line at all?) and per
        occurrence (is this mark wedged between Latin letters?).
        """
        if not self.options.persian_punctuation:
            return text

        latin = re.compile(LATIN_CHAR)
        persian = re.compile(f"[{PERSIAN_LETTERS}]")

        def convert_line(line: str) -> str:
            if len(persian.findall(line)) < 3:
                return line
            out = []
            for i, char in enumerate(line):
                replacement = self.PUNCT_MAP.get(char)
                if replacement is None:
                    out.append(char)
                    continue
                before = line[i - 1] if i else ""
                after = line[i + 1] if i + 1 < len(line) else ""
                if latin.match(before or " ") and latin.match(after or " "):
                    out.append(char)      # inside a Latin phrase
                else:
                    out.append(replacement)
            return "".join(out)

        return "\n".join(convert_line(line) for line in text.split("\n"))

    def unify_quotes(self, text: str) -> str:
        if not self.options.smart_quotes:
            return text
        text = text.replace("“", "«").replace("”", "»")
        text = text.replace("‘", "«").replace("’", "»")

        # Straight quotes: alternate open/close, but only for balanced pairs.
        def pair(match: re.Match) -> str:
            return "«" + match.group(1) + "»"

        return re.sub(r'"([^"\n]{1,400})"', pair, text)

    def fix_spacing(self, text: str) -> str:
        if not self.options.fix_spacing:
            return text
        text = re.sub(r"[ \t]+", " ", text)
        # No space before closing punctuation; exactly one after it.
        text = re.sub(rf"\s+([{re.escape(CLOSE_PUNCT)}])", r"\1", text)
        text = re.sub(rf"([{re.escape(CLOSE_PUNCT)}])(?=[^\s{re.escape(CLOSE_PUNCT + CLOSE_BRACKETS)}])", r"\1 ", text)
        # Brackets hug their contents.
        text = re.sub(rf"([{re.escape(OPEN_BRACKETS)}])\s+", r"\1", text)
        text = re.sub(rf"\s+([{re.escape(CLOSE_BRACKETS)}])", r"\1", text)
        text = re.sub(rf"([{re.escape(CLOSE_BRACKETS)}])(?=[{PERSIAN_LETTERS}])", r"\1 ", text)
        text = re.sub(rf"([{PERSIAN_LETTERS}])(?=[{re.escape(OPEN_BRACKETS)}])", r"\1 ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # -- orthography (document-aware) --------------------------------------
    #: (name, regex with two groups around the boundary) for the constructions
    #: Persian typesetters spell either with a half-space or with a space.
    AFFIX_PATTERNS = (
        ("mi", rf"(\bن?می)(?:{ZWNJ}| )([{PERSIAN_LETTERS}]{{2,}})"),
        ("ha", rf"([{PERSIAN_LETTERS}]{{2,}})(?:{ZWNJ}| )(های?|هایی|ها)\b"),
        ("tar", rf"([{PERSIAN_LETTERS}]{{2,}})(?:{ZWNJ}| )(تر|ترین)\b"),
    )

    def _document_convention(self, text: str) -> Dict[str, str]:
        """Decide, per construction, whether *this document* uses a half-space."""
        decisions: Dict[str, str] = {}
        for name, pattern in self.AFFIX_PATTERNS:
            joined = len(re.findall(pattern.replace(f"(?:{ZWNJ}| )", ZWNJ), text))
            spaced = len(re.findall(pattern.replace(f"(?:{ZWNJ}| )", " "), text))
            total = joined + spaced
            if total < 5:
                decisions[name] = "keep"
            elif joined / total >= 0.85:
                decisions[name] = "zwnj"
            elif spaced / total >= 0.85:
                decisions[name] = "space"
            else:
                decisions[name] = "keep"
        return decisions

    def fix_half_spaces(self, text: str) -> str:
        mode = self.options.half_space
        if mode == "off":
            return text
        decisions = (
            {name: "zwnj" for name, _ in self.AFFIX_PATTERNS}
            if mode == "aggressive"
            else self._document_convention(text)
        )
        for name, pattern in self.AFFIX_PATTERNS:
            decision = decisions.get(name, "keep")
            if decision == "zwnj":
                text = re.sub(pattern, rf"\1{ZWNJ}\2", text)
            elif decision == "space":
                text = re.sub(pattern, r"\1 \2", text)
        return text

    # -- entry point -------------------------------------------------------
    def apply(self, text: str) -> Tuple[str, Counter]:
        changes: Counter = Counter()
        steps = (
            ("nfc", self.to_nfc),
            ("invisibles", self.strip_invisibles),
            ("zwnj", self.normalize_zwnj),
            ("letters", self.unify_letters),
            ("digits", self.unify_digits),
            ("punctuation", self.unify_punctuation),
            ("quotes", self.unify_quotes),
            ("half_space", self.fix_half_spaces),
            ("spacing", self.fix_spacing),
        )
        for name, step in steps:
            updated = step(text)
            if updated != text:
                changes[name] += _difference_count(text, updated)
                text = updated
        return text, changes


def _difference_count(before: str, after: str) -> int:
    """Rough count of edited characters, for the report only."""
    import difflib

    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )


def normalize(text: str, options: Optional[NormalizeOptions] = None) -> str:
    return Normalizer(options).apply(text)[0]


def fold_for_compare(text: str) -> str:
    """Aggressive folding used when *comparing* two transcriptions.

    Differences in half-spaces, diacritics or digit family are not OCR errors
    worth counting, so metrics and consensus compare folded text.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.translate({ord(k): v for k, v in ARABIC_TO_PERSIAN.items()})
    text = text.translate({ord(k): v for k, v in ARABIC_INDIC_TO_LATIN.items()})
    text = text.translate({ord(k): v for k, v in PERSIAN_TO_LATIN_DIGITS.items()})
    text = text.translate({ord(ch): None for ch in INVISIBLES})
    text = re.sub(rf"[{HARAKAT}ـ{ZWNJ}]", "", text)
    text = text.replace("ة", "ه").replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = re.sub(r"[\s ]+", " ", text)
    return text.strip()
