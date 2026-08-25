"""Image conditioning: crop away app chrome, straighten, sharpen, tile.

Everything here is pure Pillow — no numpy, no OpenCV — so the tool installs
cleanly anywhere Python does.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image, ImageFilter, ImageOps


@dataclass
class Tile:
    """A slice of a page, ready to be sent to an OCR engine."""

    index: int
    total: int
    image: Image.Image
    top: int            # y offset inside the conditioned page, in pixels
    is_first: bool
    is_last: bool

    def to_bytes(self, max_bytes: int = 4_500_000) -> Tuple[bytes, str]:
        """Encode for upload; fall back to JPEG if PNG blows the 5 MB API cap."""
        buffer = io.BytesIO()
        self.image.save(buffer, format="PNG", optimize=True)
        data = buffer.getvalue()
        if len(data) <= max_bytes:
            return data, "image/png"
        for quality in (92, 85, 75):
            buffer = io.BytesIO()
            self.image.convert("L").save(buffer, format="JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            if len(data) <= max_bytes:
                break
        return data, "image/jpeg"


def _row_profile(gray: Image.Image) -> List[float]:
    """Mean brightness of every row (0-255), cheaply, via a 1-pixel-wide resize."""
    column = gray.resize((1, gray.height), Image.BILINEAR)
    return [px / 255.0 for px in column.convert("L").tobytes()]


def _column_profile(gray: Image.Image) -> List[float]:
    row = gray.resize((gray.width, 1), Image.BILINEAR)
    return [px / 255.0 for px in row.convert("L").tobytes()]


def _longest_run(flags: List[bool], max_gap: int) -> Optional[Tuple[int, int]]:
    """Longest run of True, tolerating gaps of up to `max_gap` False values."""
    best: Optional[Tuple[int, int]] = None
    start: Optional[int] = None
    end = 0
    gap = 0
    for i, flag in enumerate(flags):
        if flag:
            if start is None:
                start = i
            end = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap > max_gap:
                if best is None or (end - start) > (best[1] - best[0]):
                    best = (start, end)
                start = None
                gap = 0
    if start is not None and (best is None or (end - start) > (best[1] - best[0])):
        best = (start, end)
    return best


def _paper_level(gray: Image.Image) -> float:
    """Brightness of the page background, as the brightest well-populated mode."""
    histogram = gray.histogram()
    total = sum(histogram) or 1
    # Walk buckets from bright to dark; the first 16-wide band holding >=8% of
    # the pixels is the paper.
    for high in range(255, 15, -8):
        mass = sum(histogram[high - 15 : high + 1])
        if mass / total >= 0.08:
            return (high - 7) / 255.0
    return 0.9


def detect_content_box(image: Image.Image, min_area_ratio: float = 0.25) -> Optional[Tuple[int, int, int, int]]:
    """Locate the paper region inside a screenshot full of app chrome.

    Returns a crop box, or None when the guess is not clearly better than the
    original (we would rather send a slightly noisy page than lose a line).
    """
    gray = ImageOps.grayscale(image)
    small = gray.copy()
    small.thumbnail((320, 320 * 8), Image.BILINEAR)

    paper = _paper_level(small)
    threshold = max(0.0, paper - 0.16) * 255
    mask = small.point(lambda v, t=threshold: 255 if v >= t else 0)

    rows = _row_profile(mask)
    row_flags = [value >= 0.55 for value in rows]
    row_run = _longest_run(row_flags, max_gap=max(2, len(rows) // 50))
    if row_run is None:
        return None

    band = mask.crop((0, row_run[0], mask.width, row_run[1] + 1))
    columns = _column_profile(band)
    column_flags = [value >= 0.55 for value in columns]
    column_run = _longest_run(column_flags, max_gap=max(2, len(columns) // 50))
    if column_run is None:
        column_run = (0, mask.width - 1)

    scale_x = image.width / mask.width
    scale_y = image.height / mask.height
    left = int(column_run[0] * scale_x)
    right = int(min(image.width, (column_run[1] + 1) * scale_x))
    top = int(row_run[0] * scale_y)
    bottom = int(min(image.height, (row_run[1] + 1) * scale_y))

    if right - left < 32 or bottom - top < 32:
        return None
    area_ratio = ((right - left) * (bottom - top)) / float(image.width * image.height)
    if area_ratio < min_area_ratio:
        return None
    if area_ratio > 0.97:  # nothing meaningful to crop
        return None
    return (left, top, right, bottom)


def autocrop(image: Image.Image, margin: int = 6) -> Tuple[Image.Image, bool]:
    box = detect_content_box(image)
    if box is None:
        return image, False
    left, top, right, bottom = box
    left = max(0, left - margin)
    top = max(0, top - margin)
    right = min(image.width, right + margin)
    bottom = min(image.height, bottom + margin)
    return image.crop((left, top, right, bottom)), True


def estimate_skew(image: Image.Image, limit: float = 3.0, step: float = 0.25) -> float:
    """Estimate page rotation by maximising horizontal projection contrast.

    Text lines line up with image rows only when the page is straight, which is
    exactly when the row-brightness profile has the highest variance.
    """
    gray = ImageOps.grayscale(image)
    gray.thumbnail((700, 700 * 4), Image.BILINEAR)
    gray = ImageOps.autocontrast(gray, cutoff=2)

    best_angle, best_score = 0.0, -1.0
    angle = -limit
    while angle <= limit + 1e-9:
        rotated = gray.rotate(angle, resample=Image.BILINEAR, fillcolor=255, expand=False)
        profile = _row_profile(rotated)
        mean = sum(profile) / len(profile)
        score = sum((value - mean) ** 2 for value in profile) / len(profile)
        if score > best_score:
            best_score, best_angle = score, angle
        angle += step
    return best_angle


def deskew(image: Image.Image, min_angle: float = 0.2) -> Tuple[Image.Image, float]:
    angle = estimate_skew(image)
    if abs(angle) < min_angle:
        return image, 0.0
    return image.rotate(angle, resample=Image.BICUBIC, fillcolor=(255, 255, 255) if image.mode == "RGB" else 255,
                        expand=True), angle


def enhance(image: Image.Image) -> Image.Image:
    """Grayscale + contrast stretch + gentle sharpening.

    Persian type carries a lot of meaning in small marks (dots, the ezafe
    kasra, the half-space gap), so the sharpening is deliberately mild: heavy
    filtering merges the three dots of "پ" or "ث" into a blob.
    """
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    return gray.filter(ImageFilter.UnsharpMask(radius=1.4, percent=110, threshold=3))


def condition(
    image: Image.Image,
    *,
    do_autocrop: bool = True,
    do_deskew: bool = True,
    do_enhance: bool = True,
) -> Tuple[Image.Image, dict]:
    """Run the full conditioning chain and report what happened."""
    info = {"cropped": False, "skew_angle": 0.0, "enhanced": False}
    result = image
    if do_autocrop:
        result, info["cropped"] = autocrop(result)
    if do_deskew:
        result, info["skew_angle"] = deskew(result)
    if do_enhance:
        result = enhance(result)
        info["enhanced"] = True
    info["size"] = result.size
    return result, info


def _fit(image: Image.Image, max_edge: int) -> Image.Image:
    longest = max(image.size)
    if longest <= max_edge:
        return image
    scale = max_edge / float(longest)
    return image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.LANCZOS,
    )


def tile_page(
    image: Image.Image,
    *,
    max_edge: int = 1568,
    overlap: float = 0.14,
    aspect: float = 1.0,
    enabled: bool = True,
) -> List[Tile]:
    """Split a tall page into overlapping horizontal slices.

    The API downsamples any image whose longest edge exceeds ~1568px. On a full
    A4 scan that throws away exactly the detail Persian diacritics live in, so
    instead we cut the page into near-square slices and send each at close to
    native resolution. The slices overlap so that a text line clipped by one cut
    is always intact in its neighbour.
    """
    if not enabled or max(image.size) <= max_edge:
        return [Tile(0, 1, _fit(image, max_edge), 0, True, True)]

    tile_height = max(400, int(round(image.width * aspect)))
    if tile_height >= image.height:
        return [Tile(0, 1, _fit(image, max_edge), 0, True, True)]

    step = max(1, int(round(tile_height * (1.0 - overlap))))
    span = image.height - tile_height
    # Use the fewest full-height slices that keep every gap within `step`, then
    # spread them evenly: no sliver at the bottom, and a uniform overlap.
    count = max(2, -(-span // step) + 1)
    tops = [int(round(i * span / (count - 1))) for i in range(count)]

    tiles: List[Tile] = []
    for i, top in enumerate(tops):
        bottom = min(image.height, top + tile_height)
        crop = image.crop((0, top, image.width, bottom))
        tiles.append(
            Tile(
                index=i,
                total=len(tops),
                image=_fit(crop, max_edge),
                top=top,
                is_first=(i == 0),
                is_last=(i == len(tops) - 1),
            )
        )
    return tiles
