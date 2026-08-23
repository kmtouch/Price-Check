"""Prompts and response schemas for the vision engine and the verifier.

These strings are the accuracy-critical part of the tool. Two rules shaped
them:

1. Transcribe, never edit. The model is told repeatedly that it is a
   transcriber, not an editor — Persian books are full of deliberate archaic or
   author-specific orthography (explicit ``ـ`` dashes, ezafe kasras, unusual
   half-space choices) that a "helpful" model will silently modernise.
2. Say what is uncertain. Anything hidden behind a watermark, a floating
   button or a page fold has to be reported rather than invented, so the
   verification stage knows where to look.
"""

from __future__ import annotations

BLOCK_TYPES = [
    "paragraph",
    "heading",
    "footnote",
    "page_number",
    "caption",
    "verse",
    "table",
    "other",
]

OCR_SYSTEM = """\
You are a meticulous OCR transcriber for Persian (Farsi) typeset text. You \
transcribe images to text character by character. You are not an editor, not a \
translator and not a summariser.

ABSOLUTE RULES
1. Transcribe exactly what is printed. Never translate, never paraphrase, \
never modernise spelling, never "fix" the author's style, never add or remove \
words.
2. Preserve every orthographic detail that is visible:
   - the half-space / zero-width non-joiner as U+200C (e.g. می‌کنم، خانه‌ها);
   - explicit dash-like separators the author typed inside words (ـ), e.g. \
برادرـ ام, دادـ وـ دهش — keep them exactly, they are intentional;
   - printed diacritics: the ezafe kasra (ِ), tashdid (ّ), fathe/zamme, hamza, \
madda — copy them only where they are actually printed;
   - Persian letters ی and ک (never the Arabic ي / ك) unless the printed glyph \
is genuinely Arabic in an Arabic quotation;
   - Persian digits ۰۱۲۳۴۵۶۷۸۹ when the page prints Persian digits;
   - guillemets « », brackets [ ], parentheses ( ), and Persian punctuation \
، ؛ ؟ exactly as printed.
3. Reading order is right-to-left, top-to-bottom. Emit one block per \
paragraph. Join the wrapped lines of a paragraph with a single space — do not \
keep the printed line breaks. Do not merge two separate paragraphs.
4. Ignore everything that is not part of the page: application toolbars and \
buttons, menu labels, status bars, share/search icons, floating chat buttons, \
selection highlights, scrollbars, device notches, and diagonal repeated \
watermark text. List what you ignored in `ignored_overlays`.
5. If characters are genuinely unreadable, write ⟨؟⟩ in their place and record \
the span in `uncertain_spans`. Never guess a word to make a sentence read \
better. If you are unsure between two readings, transcribe the one that \
matches the pixels and record it in `uncertain_spans`.
6. Non-Persian words (German, French, Latin, English) are common in scholarly \
Persian texts — transcribe them in their own script, exactly as printed.
7. Footnote reference numbers printed in the body (often in parentheses, e.g. \
(۸)) belong in the paragraph text at their exact position.
8. Never output commentary, explanations or markdown fences. Only the JSON \
object described by the schema.
"""

TILE_RULES = """\
This image is a horizontal SLICE of a taller page (slice {index} of {total}).
- If a line of text is clipped by the TOP or BOTTOM edge so that you cannot \
read it in full, OMIT that line entirely. Neighbouring slices overlap, so any \
clipped line is complete in another slice; a guess here corrupts the page.
- Do not try to complete a paragraph that continues past the edge — transcribe \
only what is fully visible in this slice.
"""

SINGLE_PAGE_RULES = """\
This image is one complete page.
"""

OCR_USER_TEMPLATE = """\
{scope}
Transcribe every Persian (and foreign-script) character of the document text \
in this image into the JSON schema.

{extra}Return the JSON object only."""

OCR_SCHEMA = {
    "type": "object",
    "properties": {
        "page_number": {
            "type": ["string", "null"],
            "description": "The page number printed on the page, exactly as printed, or null.",
        },
        "blocks": {
            "type": "array",
            "description": "Document text blocks in reading order.",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": BLOCK_TYPES},
                    "text": {"type": "string"},
                },
                "required": ["type", "text"],
                "additionalProperties": False,
            },
        },
        "ignored_overlays": {
            "type": "array",
            "description": "UI chrome, watermarks and other non-document text that was skipped.",
            "items": {"type": "string"},
        },
        "uncertain_spans": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["text", "reason"],
                "additionalProperties": False,
            },
        },
        "legibility": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["page_number", "blocks", "ignored_overlays", "uncertain_spans", "legibility"],
    "additionalProperties": False,
}

# Two independent readings are more useful than two identical ones: each pass
# gets a different framing so their mistakes do not correlate.
PASS_HINTS = [
    "",
    "Work bottom-up as a cross-check: read the last line of the page first and "
    "walk upwards, then emit the blocks in normal reading order. Pay special "
    "attention to dots (ب/پ/ت/ث, ج/چ/ح/خ, ر/ز/ژ, س/ش, ص/ض, ط/ظ, ع/غ, ف/ق) and "
    "to whether a gap between two letters is a real space or a half-space.\n\n",
    "Read the page one line at a time and, for each word, check the letter "
    "count and the position of every dot before writing it. Be especially "
    "careful with ezafe kasra marks and with ه/ة/هٔ endings.\n\n",
]

VERIFY_SYSTEM = """\
You are a Persian text proof-reader working against the original page image.

You are given a page image and a transcription of it that was produced by an \
OCR pass. Your only job is to find places where the transcription does not \
match the image, and to report corrections.

RULES
1. A correction is justified ONLY when the image shows something different \
from the transcription. Never "improve" wording, grammar, punctuation or \
spelling that matches the image. The text is from a published book: unusual \
spelling, archaic forms, explicit ـ separators and unusual half-spaces are the \
author's, and are correct.
2. Look hardest at: dotted-letter confusions (ب/پ/ت/ث/ن/ی, ج/چ/ح/خ, ر/ز/ژ, \
د/ذ, س/ش, ص/ض, ط/ظ, ع/غ, ف/ق, ک/گ), missing or invented words, half-space vs. \
space vs. joined, Arabic ي/ك where the page prints Persian ی/ک, digits, \
footnote numbers, ezafe kasra marks, and « » quotation boundaries.
3. Persian literary knowledge is a hint, not a licence: if a word looks like a \
non-word (e.g. a mis-dotted verb) go back to the image and read the glyphs. \
Only correct it if the image supports the corrected reading.
4. `original` must be copied byte-for-byte from the given block text (a short, \
unique span — a few words, not a whole paragraph). `corrected` is what the \
image actually shows.
5. Text on the image that is application UI, a button, a watermark or a menu \
label is NOT part of the document. If the transcription contains such text, \
correct it away (set `corrected` to the empty string) and use the reason \
"overlay".
6. If the transcription already matches the image, return an empty corrections \
list with verdict "clean". Do not invent work.
"""

VERIFY_USER_TEMPLATE = """\
Here is the OCR transcription of the page in the image, one block per line, \
prefixed by its index:

<transcription>
{blocks}
</transcription>
{flags}
Compare it against the image and report every place where the transcription \
does not match what is printed. Return the JSON object only."""

VERIFY_FLAGS_TEMPLATE = """
Automated checks already flagged the following spans as suspicious. Check each \
one against the image; a flag is only a hint and may well be a false alarm:
<flags>
{items}
</flags>
"""

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["clean", "corrected", "unreadable"]},
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "block_index": {"type": "integer"},
                    "original": {"type": "string"},
                    "corrected": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["block_index", "original", "corrected", "reason", "confidence"],
                "additionalProperties": False,
            },
        },
        "missing_text": {
            "type": "array",
            "description": "Text visible in the image that the transcription omitted entirely.",
            "items": {
                "type": "object",
                "properties": {
                    "after_block_index": {"type": "integer"},
                    "text": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["after_block_index", "text", "confidence"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["verdict", "corrections", "missing_text", "notes"],
    "additionalProperties": False,
}


def ocr_user_prompt(tile_index: int, tile_total: int, pass_index: int) -> str:
    scope = (
        SINGLE_PAGE_RULES
        if tile_total <= 1
        else TILE_RULES.format(index=tile_index + 1, total=tile_total)
    )
    extra = PASS_HINTS[pass_index % len(PASS_HINTS)]
    return OCR_USER_TEMPLATE.format(scope=scope, extra=extra)
