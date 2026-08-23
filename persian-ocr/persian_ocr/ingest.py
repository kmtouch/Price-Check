"""Turn whatever the user points at into an ordered list of page images."""

from __future__ import annotations

import glob
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from PIL import Image

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | PDF_SUFFIXES

# Pillow refuses very large images by default (decompression-bomb guard). Page
# scans at 600 dpi legitimately exceed it, so raise the ceiling deliberately.
Image.MAX_IMAGE_PIXELS = 300_000_000


class IngestError(RuntimeError):
    pass


@dataclass
class Page:
    """One page of source material, already decoded into a Pillow image."""

    index: int              # 0-based position in the whole job
    source: Path
    source_page: int        # 0-based page within `source` (0 for standalone images)
    image: Image.Image

    @property
    def label(self) -> str:
        if self.source.suffix.lower() in PDF_SUFFIXES:
            return f"{self.source.name}#{self.source_page + 1}"
        return self.source.name


def _natural_key(path: Path):
    """Sort page-2 before page-10 the way a human would."""
    parts = re.split(r"(\d+)", path.name)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def expand_inputs(inputs: Sequence[str]) -> List[Path]:
    """Expand files, directories and globs into a stable, ordered file list."""
    found: List[Path] = []
    for raw in inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            found.extend(
                sorted(
                    (p for p in path.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES),
                    key=_natural_key,
                )
            )
        elif path.exists():
            found.append(path)
        else:
            matches = sorted((Path(m) for m in glob.glob(raw, recursive=True)), key=_natural_key)
            if not matches:
                raise IngestError(f"input not found: {raw}")
            found.extend(m for m in matches if m.suffix.lower() in SUPPORTED_SUFFIXES)

    if not found:
        raise IngestError("no supported input files (pdf/png/jpg/webp/tiff/bmp) were found")

    unsupported = [p for p in found if p.suffix.lower() not in SUPPORTED_SUFFIXES]
    if unsupported:
        raise IngestError(f"unsupported file type: {unsupported[0]}")
    return found


def _pdf_pages(path: Path, dpi: int, pages: Optional[Iterable[int]]) -> List[Image.Image]:
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover - exercised only without the dep
        try:
            import fitz as pymupdf  # type: ignore
        except ImportError as exc:
            raise IngestError(
                "reading PDFs needs PyMuPDF — install it with `pip install pymupdf`"
            ) from exc

    out: List[Image.Image] = []
    with pymupdf.open(path) as doc:
        wanted = range(doc.page_count) if pages is None else pages
        for number in wanted:
            if number < 0 or number >= doc.page_count:
                raise IngestError(f"{path.name} has no page {number + 1}")
            pixmap = doc.load_page(number).get_pixmap(dpi=dpi, alpha=False)
            out.append(Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB"))
    return out


def pdf_has_text_layer(path: Path, min_chars: int = 40) -> bool:
    """True when the PDF already carries selectable text worth extracting.

    Running OCR over a born-digital PDF is strictly worse than reading its text
    layer, so the CLI checks this and tells the user.
    """
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover
        try:
            import fitz as pymupdf  # type: ignore
        except ImportError:
            return False
    try:
        with pymupdf.open(path) as doc:
            for number in range(min(doc.page_count, 5)):
                if len(doc.load_page(number).get_text("text").strip()) >= min_chars:
                    return True
    except Exception:
        return False
    return False


def extract_pdf_text(path: Path) -> str:
    """Read an existing PDF text layer (used by ``--prefer-text-layer``)."""
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover
        import fitz as pymupdf  # type: ignore
    chunks = []
    with pymupdf.open(path) as doc:
        for number in range(doc.page_count):
            chunks.append(doc.load_page(number).get_text("text"))
    return "\n\n".join(chunks)


def load_pages(
    paths: Sequence[Path],
    dpi: int = 300,
    page_selection: Optional[Iterable[int]] = None,
) -> List[Page]:
    """Decode every input into `Page` objects, in reading order.

    `page_selection` is 0-based and only applies when a single PDF is given.
    """
    selection = list(page_selection) if page_selection is not None else None
    if selection is not None and (len(paths) != 1 or paths[0].suffix.lower() not in PDF_SUFFIXES):
        raise IngestError("--pages can only be used with a single PDF input")

    pages: List[Page] = []
    for path in paths:
        suffix = path.suffix.lower()
        if suffix in PDF_SUFFIXES:
            for offset, image in enumerate(_pdf_pages(path, dpi, selection)):
                source_page = selection[offset] if selection else offset
                pages.append(Page(len(pages), path, source_page, image))
        else:
            try:
                image = Image.open(path)
                image.load()
            except Exception as exc:
                raise IngestError(f"could not read image {path}: {exc}") from exc
            if getattr(image, "n_frames", 1) > 1:  # multi-page TIFF
                for frame in range(image.n_frames):
                    image.seek(frame)
                    pages.append(Page(len(pages), path, frame, image.convert("RGB")))
            else:
                pages.append(Page(len(pages), path, 0, image.convert("RGB")))
    return pages


def parse_page_selection(spec: str) -> List[int]:
    """Parse ``"1-3,7,9-10"`` (1-based, inclusive) into 0-based indices."""
    result: List[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, _, end = chunk.partition("-")
            try:
                lo, hi = int(start), int(end)
            except ValueError as exc:
                raise IngestError(f"bad page range: {chunk!r}") from exc
            if lo < 1 or hi < lo:
                raise IngestError(f"bad page range: {chunk!r}")
            result.extend(range(lo - 1, hi))
        else:
            try:
                number = int(chunk)
            except ValueError as exc:
                raise IngestError(f"bad page number: {chunk!r}") from exc
            if number < 1:
                raise IngestError(f"bad page number: {chunk!r}")
            result.append(number - 1)
    if not result:
        raise IngestError("empty page selection")
    return sorted(dict.fromkeys(result))
