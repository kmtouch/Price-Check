"""OCR engine implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Block, EngineError, OcrEngine, PageReading

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Settings

__all__ = [
    "Block", "EngineError", "OcrEngine", "PageReading",
    "build_engine", "available_engines", "resolve_engine",
]


def available_engines() -> list:
    return ["auto", "claude-cli", "anthropic", "tesseract", "mock"]


def resolve_engine(name: str) -> str:
    """Turn ``auto`` into a concrete engine.

    Preference order: an API key if one is configured, otherwise a signed-in
    Claude Code CLI (no key needed), otherwise a local Tesseract. Whichever is
    chosen, the caller is told which one it got.
    """
    if name != "auto":
        return name
    import os
    import shutil

    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    if shutil.which(os.environ.get("PERSIAN_OCR_CLAUDE_BIN") or "claude"):
        return "claude-cli"
    if shutil.which("tesseract"):
        return "tesseract"
    raise EngineError(
        "no engine is available. Either set ANTHROPIC_API_KEY, or install and "
        "sign in to Claude Code (`claude`) which needs no API key, or install "
        "tesseract with its Persian data for offline use."
    )


def build_engine(settings: "Settings") -> OcrEngine:
    name = resolve_engine(settings.engine.lower())
    if name in ("claude-cli", "claude_cli", "cli"):
        from .claude_cli import ClaudeCliEngine

        return ClaudeCliEngine(settings)
    if name == "anthropic":
        from .anthropic_vision import AnthropicVisionEngine

        return AnthropicVisionEngine(settings)
    if name == "tesseract":
        from .tesseract_engine import TesseractEngine

        return TesseractEngine(settings)
    if name == "mock":
        from .mock import MockEngine

        return MockEngine(settings)
    raise EngineError(f"unknown engine {settings.engine!r} (choose from {', '.join(available_engines())})")
