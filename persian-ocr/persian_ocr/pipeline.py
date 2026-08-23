"""The end-to-end conversion pipeline.

    ingest → condition → tile → N OCR passes → consensus
           → checks (rules + vocabulary) → verify against the image
           → normalise → assemble → report

Every stage is independently testable; this module is only the wiring, the
concurrency and the bookkeeping.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .assemble import PageResult, merge_tiles, paragraph_stats, render_document
from .cache import Cache
from .config import Settings
from .consensus import reconcile
from .engines import build_engine
from .engines.base import Block, EngineError, OcrEngine, PageReading
from .ingest import Page, load_pages
from .lexicon import Lexicon
from .normalize import NormalizeOptions, Normalizer
from .preprocess import Tile, condition, tile_page
from .verify import (
    Correction,
    apply_corrections,
    apply_missing_text,
    confidence_score,
    parse_corrections,
    run_checks,
)

ProgressFn = Callable[[str], None]


@dataclass
class RunResult:
    text: str
    pages: List[PageResult] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)
    settings: Optional[Settings] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        if not self.pages:
            return 0.0
        weights = [max(1, len(page.text.split())) for page in self.pages]
        total = sum(weights)
        return sum(p.confidence * w for p, w in zip(self.pages, weights)) / total

    def low_confidence_pages(self, threshold: float = 0.9) -> List[PageResult]:
        return [page for page in self.pages if page.confidence < threshold]


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        engine: Optional[OcrEngine] = None,
        progress: Optional[ProgressFn] = None,
    ):
        self.settings = settings
        self.engine = engine or build_engine(settings)
        self.cache = Cache(settings.cache_dir, settings.use_cache)
        self.progress = progress or (lambda message: None)
        self.usage = {"input_tokens": 0, "output_tokens": 0, "requests": 0}
        self.warnings: List[str] = []

    # -- engine plumbing ---------------------------------------------------
    def _read_tile(self, tile: Tile, pass_index: int) -> PageReading:
        image_bytes, media_type = tile.to_bytes()
        key = self.cache.key(
            image_bytes,
            kind="read",
            engine=self.engine.name,
            model=self.settings.model,
            tile=tile.index,
            total=tile.total,
            pass_index=pass_index,
            effort=self.settings.ocr_effort,
        )
        cached = self.cache.get(key)
        if cached is not None:
            return PageReading.from_dict(cached)

        reading = self.engine.read(
            image_bytes,
            media_type,
            tile_index=tile.index,
            tile_total=tile.total,
            pass_index=pass_index,
        )
        self._account(reading.usage)
        self.cache.put(key, reading.to_dict())
        return reading

    def _account(self, usage: Dict) -> None:
        self.usage["requests"] += 1
        self.usage["input_tokens"] += usage.get("input_tokens", 0)
        self.usage["output_tokens"] += usage.get("output_tokens", 0)

    # -- one page ----------------------------------------------------------
    def process_page(self, page: Page, lexicon: Lexicon) -> PageResult:
        started = time.time()
        image, info = condition(
            page.image,
            do_autocrop=self.settings.autocrop,
            do_deskew=self.settings.deskew,
            do_enhance=self.settings.enhance,
        )
        tiles = tile_page(
            image,
            max_edge=self.settings.max_edge,
            overlap=self.settings.tile_overlap,
            enabled=self.settings.tile,
        )
        self.progress(f"page {page.index + 1} ({page.label}): {len(tiles)} tile(s) × {self.settings.passes} pass(es)")

        result = PageResult(index=page.index, label=page.label)
        if info["cropped"]:
            result.notes.append("cropped away the surrounding application chrome")
        if info["skew_angle"]:
            result.notes.append(f"straightened by {info['skew_angle']:.2f}°")

        tile_blocks: List[List[Block]] = []
        agreements: List[float] = []
        consensus_flags: List[str] = []
        overlays: List[str] = []
        legibilities: List[str] = []

        for tile in tiles:
            readings: List[PageReading] = []
            errors: List[str] = []
            for pass_index in range(max(1, self.settings.passes)):
                try:
                    readings.append(self._read_tile(tile, pass_index))
                except EngineError as exc:
                    errors.append(str(exc))
            if not readings:
                raise EngineError(
                    f"could not read {page.label} tile {tile.index + 1}: {errors[0] if errors else 'unknown error'}"
                )
            if errors:
                result.notes.append(f"tile {tile.index + 1}: {len(errors)} pass(es) failed — {errors[0]}")

            merged = reconcile(readings)
            tile_blocks.append(merged.blocks)
            agreements.append(merged.agreement)
            overlays.extend(merged.ignored_overlays)
            legibilities.append(merged.legibility)
            if merged.structure_mismatch:
                consensus_flags.append(f"tile {tile.index + 1}: the passes split the page into different blocks")
            consensus_flags.extend(d.describe() for d in merged.disagreements)
            if merged.page_number and not result.page_number:
                result.page_number = merged.page_number
            for span in merged.uncertain_spans:
                consensus_flags.append(
                    f"the engine was unsure of “{span.get('text', '')}” ({span.get('reason', '')})"
                )

        result.blocks = merge_tiles(tile_blocks)
        result.agreement = sum(agreements) / len(agreements) if agreements else 1.0
        result.ignored_overlays = list(dict.fromkeys(overlays))
        result.legibility = min(legibilities or ["high"], key=lambda x: ["high", "medium", "low"].index(x))

        # -- verification --------------------------------------------------
        checks = run_checks(result.blocks, lexicon, consensus_flags)
        result.flags = list(checks.flags)
        corrections: List[Correction] = []

        if self.settings.verify and getattr(self.engine, "supports_verification", False):
            corrections = self._verify_page(page, tiles, result, checks, lexicon)
        elif self.settings.verify:
            self.warnings.append(
                f"the {self.engine.name} engine cannot verify against the image; "
                "rule and vocabulary checks still ran"
            )

        result.corrections = [c.to_dict() for c in corrections]
        applied = [c for c in corrections if c.applied]
        if applied:
            result.notes.append(f"verification changed {len(applied)} span(s)")

        final_checks = run_checks(result.blocks, lexicon, [])
        result.flags = final_checks.flags
        result.confidence = confidence_score(
            agreement=result.agreement,
            lexicon_coverage=final_checks.lexicon_coverage,
            structural_problems=len(final_checks.structural),
            unresolved_flags=len(final_checks.vocabulary),
            words=len(result.text.split()),
            legibility=result.legibility,
        )
        result.usage = {"seconds": round(time.time() - started, 2)}
        return result

    def _verify_page(
        self,
        page: Page,
        tiles: Sequence[Tile],
        result: PageResult,
        checks,
        lexicon: Lexicon,
    ) -> List[Correction]:
        """Re-read the page against its images, up to `verify_rounds` times.

        All the tiles go into one request, so the verifier sees the whole page
        at full glyph resolution while the block indices it is asked about
        refer to the already-assembled page text.
        """
        all_corrections: List[Correction] = []
        images = [tile.to_bytes() for tile in tiles]
        fingerprint = self.cache.key(b"".join(data for data, _ in images), kind="page")

        flags = list(checks.flags)
        for round_index in range(max(1, self.settings.verify_rounds)):
            if round_index and not flags:
                break
            key = self.cache.key(
                fingerprint.encode(),
                kind="verify",
                model=self.settings.verify_model,
                text="\n".join(b.text for b in result.blocks),
                effort=self.settings.verify_effort,
            )
            payload = self.cache.get(key)
            if payload is None:
                try:
                    payload = self.engine.verify(images, result.blocks, flags)
                except EngineError as exc:
                    result.notes.append(f"verification round {round_index + 1} failed: {exc}")
                    break
                self._account(payload.pop("_usage", {}))
                self.cache.put(key, payload)

            corrections = parse_corrections(payload)
            result.blocks, processed = apply_corrections(
                result.blocks,
                corrections,
                min_confidence=self.settings.min_correction_confidence,
                max_drift=self.settings.max_correction_drift,
                max_changed_words=self.settings.max_changed_words,
                already_applied=[
                    (c.original, c.corrected) for c in all_corrections if c.applied
                ],
            )
            result.blocks, added = apply_missing_text(
                result.blocks, payload, self.settings.min_correction_confidence
            )
            result.notes.extend(added)
            all_corrections.extend(processed)

            if payload.get("notes"):
                result.notes.append(f"verifier: {payload['notes']}")
            applied = [c for c in processed if c.applied]
            self.progress(
                f"page {page.index + 1}: verification round {round_index + 1} "
                f"applied {len(applied)}/{len(processed)} correction(s)"
            )
            if not applied and not added:
                break
            flags = run_checks(result.blocks, lexicon, []).flags
        return all_corrections

    # -- whole run ---------------------------------------------------------
    def run(self, inputs: Sequence[Path], page_selection: Optional[Sequence[int]] = None) -> RunResult:
        started = time.time()
        pages = load_pages(list(inputs), dpi=self.settings.dpi, page_selection=page_selection)
        self.progress(f"loaded {len(pages)} page(s) from {len(set(p.source for p in pages))} file(s)")

        lexicon = Lexicon(tuple(self.settings.lexicon_paths))

        results: List[PageResult] = [None] * len(pages)  # type: ignore[list-item]
        workers = max(1, min(self.settings.workers, len(pages)))
        if workers == 1:
            for page in pages:
                results[page.index] = self.process_page(page, lexicon)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(self.process_page, page, lexicon): page for page in pages}
                for future, page in futures.items():
                    results[page.index] = future.result()

        # A second lexicon pass now knows the document's own vocabulary, which
        # makes the reported flags far less noisy than the per-page pass.
        draft = "\n\n".join(page.text for page in results)
        document_lexicon = Lexicon(tuple(self.settings.lexicon_paths), document_text=draft)
        for page in results:
            page.flags = run_checks(page.blocks, document_lexicon, []).flags

        text = render_document(
            results,
            page_marks="number" if self.settings.keep_page_numbers else "none",
            join_pages=self.settings.join_pages,
            page_separator=self.settings.page_separator,
        )

        if self.settings.normalize:
            normalizer = Normalizer(
                NormalizeOptions(
                    persian_digits=self.settings.persian_digits,
                    persian_punctuation=self.settings.persian_punctuation,
                )
            )
            text, changes = normalizer.apply(text)
        else:
            changes = {}
        if text and not text.endswith("\n"):
            text += "\n"

        stats = paragraph_stats(text)
        stats.update(
            {
                "pages": len(results),
                "seconds": round(time.time() - started, 2),
                "normalisation": dict(changes),
                "usage": dict(self.usage),
                "cache": self.cache.stats(),
                "engine": self.engine.name,
                "model": self.settings.model if self.engine.name == "anthropic" else self.engine.name,
                "lexicon_coverage": round(document_lexicon.coverage(text), 4),
            }
        )
        return RunResult(
            text=text, pages=results, stats=stats, settings=self.settings, warnings=list(self.warnings)
        )
