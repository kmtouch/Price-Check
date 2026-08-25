"""Runtime settings for the pipeline.

Every knob the CLI exposes lives here so that the pipeline, the engines and the
web UI all read from one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional, Sequence

# Bump whenever a prompt or the response schema changes: the value is part of
# the cache key, so old cached transcriptions are ignored instead of reused.
PROMPT_VERSION = "3"

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_VERIFY_MODEL = "claude-opus-5"

#: Models that accept ``output_config.effort`` and adaptive thinking.
EFFORT_CAPABLE_PREFIXES = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
)

#: Models where a safety refusal can be routed to a fallback model server-side.
FALLBACK_CAPABLE_PREFIXES = ("claude-opus-5", "claude-fable-5", "claude-mythos-5")


def supports_effort(model: str) -> bool:
    return model.startswith(EFFORT_CAPABLE_PREFIXES)


def supports_server_fallback(model: str) -> bool:
    return model.startswith(FALLBACK_CAPABLE_PREFIXES)


@dataclass
class Settings:
    """Everything the pipeline needs to know, in one immutable-ish bundle."""

    # --- engines -----------------------------------------------------------
    engine: str = "auto"
    model: str = DEFAULT_MODEL
    verify_model: str = DEFAULT_VERIFY_MODEL
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    passes: int = 2
    ocr_effort: str = "medium"
    verify_effort: str = "high"
    max_tokens: int = 16000
    server_fallbacks: bool = True
    request_timeout: float = 300.0
    max_retries: int = 4

    # --- rasterisation / image conditioning --------------------------------
    dpi: int = 300
    max_edge: int = 1568          # Anthropic downsizes anything larger anyway
    tile_overlap: float = 0.14    # fraction of tile height repeated in the next tile
    tile: bool = True
    deskew: bool = True
    enhance: bool = True
    autocrop: bool = True

    # --- verification ------------------------------------------------------
    verify: bool = True
    verify_rounds: int = 2
    min_correction_confidence: float = 0.75
    max_correction_drift: float = 0.4   # reject wholesale rewrites
    max_changed_words: int = 2          # a fix touches a word or two, not a clause
    lexicon_paths: Sequence[Path] = field(default_factory=tuple)

    # --- text shaping ------------------------------------------------------
    normalize: bool = True
    persian_digits: bool = True
    persian_punctuation: bool = True
    keep_page_numbers: bool = True
    page_separator: str = "\n\n"
    join_pages: bool = True       # stitch a paragraph split across a page break
    strip_repeated_boundaries: bool = False  # drop running headers/footers/watermarks

    # --- plumbing ----------------------------------------------------------
    workers: int = 4
    cache_dir: Optional[Path] = None
    use_cache: bool = True
    quiet: bool = False

    def resolved_api_key(self) -> Optional[str]:
        return self.api_key or os.environ.get("ANTHROPIC_API_KEY")

    def with_(self, **kwargs) -> "Settings":
        return replace(self, **kwargs)
