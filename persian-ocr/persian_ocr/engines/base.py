"""The contract every OCR engine implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple


class EngineError(RuntimeError):
    """Raised when an engine cannot produce a reading at all."""


@dataclass
class Block:
    type: str
    text: str


@dataclass
class PageReading:
    """One engine's reading of one tile."""

    blocks: List[Block] = field(default_factory=list)
    page_number: Optional[str] = None
    ignored_overlays: List[str] = field(default_factory=list)
    uncertain_spans: List[Dict[str, str]] = field(default_factory=list)
    legibility: str = "high"
    usage: Dict[str, int] = field(default_factory=dict)
    engine: str = ""
    raw: Optional[Dict[str, Any]] = None

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks if block.text.strip())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "blocks": [{"type": b.type, "text": b.text} for b in self.blocks],
            "page_number": self.page_number,
            "ignored_overlays": list(self.ignored_overlays),
            "uncertain_spans": list(self.uncertain_spans),
            "legibility": self.legibility,
            "usage": dict(self.usage),
            "engine": self.engine,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PageReading":
        return cls(
            blocks=[Block(b.get("type", "paragraph"), b.get("text", "")) for b in data.get("blocks", [])],
            page_number=data.get("page_number"),
            ignored_overlays=list(data.get("ignored_overlays", [])),
            uncertain_spans=list(data.get("uncertain_spans", [])),
            legibility=data.get("legibility", "high"),
            usage=dict(data.get("usage", {})),
            engine=data.get("engine", ""),
            raw=data,
        )


class OcrEngine(Protocol):
    """Reads one image and returns structured text."""

    name: str

    def read(
        self,
        image_bytes: bytes,
        media_type: str,
        *,
        tile_index: int = 0,
        tile_total: int = 1,
        pass_index: int = 0,
    ) -> PageReading:
        ...

    def verify(
        self,
        images: List[Tuple[bytes, str]],
        blocks: List[Block],
        flags: List[str],
    ) -> Dict[str, Any]:
        """Re-read the page images against `blocks` and propose corrections.

        `images` is the page's tiles in reading order, each as
        ``(bytes, media_type)`` — sending the tiles rather than one shrunken
        page keeps the glyph detail the check depends on.
        """
        ...

    @property
    def supports_verification(self) -> bool:
        ...
