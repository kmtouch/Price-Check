"""On-disk cache of engine responses.

OCR calls are the expensive part of a run. Keying the cache on the *image
bytes* (not the file path) means a re-run after tweaking output options, an
interrupted job, or a second pass over the same pages costs nothing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

from .config import PROMPT_VERSION


class Cache:
    def __init__(self, directory: Optional[Path], enabled: bool = True):
        self.directory = Path(directory) if directory else None
        self.enabled = enabled and self.directory is not None
        self.hits = 0
        self.misses = 0
        if self.enabled:
            self.directory.mkdir(parents=True, exist_ok=True)

    def key(self, image_bytes: bytes, **parts: Any) -> str:
        digest = hashlib.sha256()
        digest.update(image_bytes)
        digest.update(PROMPT_VERSION.encode())
        for name in sorted(parts):
            digest.update(f"|{name}={parts[name]}".encode())
        return digest.hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> Optional[Dict]:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.exists():
            self.misses += 1
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.misses += 1
            return None
        self.hits += 1
        return data

    def put(self, key: str, value: Dict) -> None:
        if not self.enabled:
            return
        try:
            self._path(key).write_text(
                json.dumps(value, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass  # a cache miss is never a reason to fail a run

    def stats(self) -> Dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
