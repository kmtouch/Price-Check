"""Replay engine used by the test-suite and by `--engine mock` demos.

Reads canned responses from a directory of JSON files instead of calling an
API, which makes the whole pipeline — consensus, verification, reporting —
testable offline and deterministic.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import Settings
from .base import Block, EngineError, PageReading


class MockEngine:
    name = "mock"

    def __init__(self, settings: Settings, fixtures: Optional[Path] = None,
                 reader: Optional[Callable[..., PageReading]] = None,
                 verifier: Optional[Callable[..., Dict[str, Any]]] = None):
        self.settings = settings
        self.fixtures = fixtures or Path(os.environ.get("PERSIAN_OCR_FIXTURES", "fixtures"))
        self._reader = reader
        self._verifier = verifier
        self.calls: List[Dict[str, Any]] = []

    @property
    def supports_verification(self) -> bool:
        return self._verifier is not None or (self.fixtures / "verify").is_dir()

    def _load(self, kind: str, key: str) -> Dict[str, Any]:
        path = self.fixtures / kind / f"{key}.json"
        if not path.exists():
            raise EngineError(f"no mock fixture for {kind}/{key}")
        return json.loads(path.read_text(encoding="utf-8"))

    def read(
        self,
        image_bytes: bytes,
        media_type: str,
        *,
        tile_index: int = 0,
        tile_total: int = 1,
        pass_index: int = 0,
    ) -> PageReading:
        self.calls.append({"kind": "read", "tile": tile_index, "pass": pass_index})
        if self._reader is not None:
            return self._reader(
                image_bytes, media_type, tile_index=tile_index,
                tile_total=tile_total, pass_index=pass_index,
            )
        digest = hashlib.sha256(image_bytes).hexdigest()[:12]
        data = self._load("read", f"{digest}-t{tile_index}-p{pass_index}")
        reading = PageReading.from_dict(data)
        reading.engine = self.name
        return reading

    def verify(
        self,
        images: List[Tuple[bytes, str]],
        blocks: List[Block],
        flags: List[str],
    ) -> Dict[str, Any]:
        self.calls.append({"kind": "verify", "flags": list(flags)})
        if self._verifier is not None:
            return self._verifier(images, blocks, flags)
        digest = hashlib.sha256(images[0][0]).hexdigest()[:12]
        return self._load("verify", digest)
