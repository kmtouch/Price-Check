"""OCR engine implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Block, EngineError, OcrEngine, PageReading

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Settings

__all__ = ["Block", "EngineError", "OcrEngine", "PageReading", "build_engine", "available_engines"]


def available_engines() -> list:
    return ["anthropic", "tesseract", "mock"]


def build_engine(settings: "Settings") -> OcrEngine:
    name = settings.engine.lower()
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
