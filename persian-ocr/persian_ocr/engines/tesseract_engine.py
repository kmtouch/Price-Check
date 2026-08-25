"""Offline fallback engine built on Tesseract's Persian model.

Considerably less accurate than the vision engine on book typography — it has
no notion of the half-space and tends to drop diacritics — but it needs no
network and no API key, and it is useful as an independent second opinion:
where Tesseract and the vision model agree, confidence is high.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..config import Settings
from .base import Block, EngineError, PageReading


class TesseractEngine:
    name = "tesseract"

    def __init__(self, settings: Settings):
        self.settings = settings
        if shutil.which("tesseract") is None:
            raise EngineError(
                "tesseract is not installed. On Debian/Ubuntu: "
                "`sudo apt install tesseract-ocr tesseract-ocr-fas`"
            )

    @property
    def supports_verification(self) -> bool:
        return False

    def read(
        self,
        image_bytes: bytes,
        media_type: str,
        *,
        tile_index: int = 0,
        tile_total: int = 1,
        pass_index: int = 0,
    ) -> PageReading:
        suffix = ".png" if media_type.endswith("png") else ".jpg"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / f"page{suffix}"
            source.write_bytes(image_bytes)
            try:
                completed = subprocess.run(
                    ["tesseract", str(source), "stdout", "-l", "fas", "--psm", "6"],
                    capture_output=True,
                    check=True,
                    timeout=300,
                )
            except subprocess.CalledProcessError as exc:
                raise EngineError(f"tesseract failed: {exc.stderr.decode('utf-8', 'replace')[:300]}") from exc
            except subprocess.TimeoutExpired as exc:
                raise EngineError("tesseract timed out") from exc

        text = completed.stdout.decode("utf-8", "replace")
        blocks = [
            Block("paragraph", " ".join(chunk.split()))
            for chunk in text.split("\n\n")
            if chunk.strip()
        ]
        return PageReading(
            blocks=blocks,
            legibility="medium",
            engine=self.name,
        )

    def verify(
        self,
        images: List[Tuple[bytes, str]],
        blocks: List[Block],
        flags: List[str],
    ) -> Dict[str, Any]:
        raise EngineError("the tesseract engine cannot verify; use --engine anthropic")
