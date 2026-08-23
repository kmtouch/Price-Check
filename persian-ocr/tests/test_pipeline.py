"""End-to-end pipeline tests driven by a scripted engine.

The engine is replaced with one whose answers we control, so the whole chain —
tiling, two passes, consensus, checks, verification, vetting, normalisation,
assembly, reporting — runs for real against a real page image without a network
call.
"""

import pytest

from persian_ocr.config import Settings
from persian_ocr.engines.base import Block, EngineError, PageReading
from persian_ocr.engines.mock import MockEngine
from persian_ocr.pipeline import Pipeline

GOOD = "نیچه همیشه بسیار فشرده و «جنگی» چیز می‌نویسد تا جایی که به نظر می‌رسد."
MISREAD = "نیچه همیشه بسیار فشرده و «جنگی» چیز می‌نویسد تا جایی که به نظر می‌رسذ."


def settings(**overrides) -> Settings:
    base = dict(
        engine="mock", passes=2, verify=False, workers=1, use_cache=False,
        tile=False, deskew=False, autocrop=False, enhance=False,
    )
    base.update(overrides)
    return Settings(**base)


def scripted(texts_by_pass, verifier=None):
    """Build a mock engine that answers each pass with the given text."""

    def reader(image_bytes, media_type, *, tile_index=0, tile_total=1, pass_index=0):
        text = texts_by_pass[pass_index % len(texts_by_pass)]
        return PageReading(blocks=[Block("paragraph", text)], engine="mock")

    def make(config: Settings):
        return MockEngine(config, reader=reader, verifier=verifier)

    return make


def test_a_clean_page_converts_and_scores_high(sample_image):
    config = settings()
    pipeline = Pipeline(config, engine=scripted([GOOD, GOOD])(config))
    result = pipeline.run([sample_image])

    assert GOOD.rstrip(".") in result.text
    assert result.pages[0].agreement == 1.0
    assert result.confidence > 0.9
    assert result.stats["pages"] == 1


def test_passes_that_disagree_lower_the_confidence(sample_image):
    config = settings()
    pipeline = Pipeline(config, engine=scripted([GOOD, MISREAD])(config))
    result = pipeline.run([sample_image])

    assert result.pages[0].agreement < 1.0
    assert result.confidence < 1.0


def test_verification_fixes_a_misreading(sample_image):
    def verifier(images, blocks, flags):
        assert images and isinstance(images[0][0], bytes)
        return {
            "verdict": "corrected",
            "corrections": [
                {
                    "block_index": 0,
                    "original": "می‌رسذ",
                    "corrected": "می‌رسد",
                    "reason": "the page shows a dotless dal",
                    "confidence": 0.96,
                }
            ],
            "missing_text": [],
            "notes": "",
        }

    config = settings(verify=True, verify_rounds=1)
    pipeline = Pipeline(config, engine=scripted([MISREAD, MISREAD], verifier)(config))
    result = pipeline.run([sample_image])

    assert "می‌رسد" in result.text
    assert "می‌رسذ" not in result.text
    applied = [c for c in result.pages[0].corrections if c["applied"]]
    assert len(applied) == 1


def test_verification_is_not_allowed_to_rewrite_the_text(sample_image):
    def verifier(images, blocks, flags):
        return {
            "verdict": "corrected",
            "corrections": [
                {
                    "block_index": 0,
                    "original": GOOD,
                    "corrected": "نیچه معمولاً خیلی خلاصه و روان می‌نوشت و همین بس.",
                    "reason": "reads better",
                    "confidence": 0.99,
                }
            ],
            "missing_text": [],
            "notes": "",
        }

    config = settings(verify=True, verify_rounds=1)
    pipeline = Pipeline(config, engine=scripted([GOOD, GOOD], verifier)(config))
    result = pipeline.run([sample_image])

    assert "خلاصه و روان" not in result.text
    rejected = [c for c in result.pages[0].corrections if not c["applied"]]
    assert rejected and rejected[0]["rejected_because"]


def test_flags_are_handed_to_the_verifier(sample_image):
    seen = {}

    def verifier(images, blocks, flags):
        seen["flags"] = list(flags)
        return {"verdict": "clean", "corrections": [], "missing_text": [], "notes": ""}

    config = settings(verify=True, verify_rounds=1)
    pipeline = Pipeline(config, engine=scripted([GOOD, MISREAD], verifier)(config))
    pipeline.run([sample_image])

    assert any("می‌رسذ" in flag or "رسذ" in flag for flag in seen["flags"])


def test_application_chrome_is_flagged_on_the_page(sample_image):
    text = "متنِ کتاب اینجاست Edit PDF Continue"
    config = settings()
    pipeline = Pipeline(config, engine=scripted([text, text])(config))
    result = pipeline.run([sample_image])
    assert any("chrome" in flag for flag in result.pages[0].flags)


def test_a_failing_pass_does_not_sink_the_page(sample_image):
    calls = {"n": 0}

    def reader(image_bytes, media_type, *, tile_index=0, tile_total=1, pass_index=0):
        calls["n"] += 1
        if pass_index == 1:
            raise EngineError("simulated failure")
        return PageReading(blocks=[Block("paragraph", GOOD)])

    config = settings()
    pipeline = Pipeline(config, engine=MockEngine(config, reader=reader))
    result = pipeline.run([sample_image])
    assert GOOD.rstrip(".") in result.text
    assert any("failed" in note for note in result.pages[0].notes)


def test_every_pass_failing_is_an_error(sample_image):
    def reader(*args, **kwargs):
        raise EngineError("no")

    config = settings()
    pipeline = Pipeline(config, engine=MockEngine(config, reader=reader))
    with pytest.raises(EngineError):
        pipeline.run([sample_image])


def test_results_are_cached_between_runs(sample_image, tmp_path):
    config = settings(use_cache=True, cache_dir=tmp_path / "cache")
    engine = scripted([GOOD, GOOD])(config)

    Pipeline(config, engine=engine).run([sample_image])
    first_calls = len(engine.calls)
    Pipeline(config, engine=engine).run([sample_image])

    assert len(engine.calls) == first_calls  # the second run hit the cache only


def test_multiple_pages_keep_their_order(samples_dir):
    images = sorted((samples_dir / "images").glob("*.jpg"))
    texts = {}

    def reader(image_bytes, media_type, *, tile_index=0, tile_total=1, pass_index=0):
        marker = f"صفحهٔ شماره {len(texts) // 2 + 1} با متنِ آزمایشی."
        texts[len(texts)] = marker
        return PageReading(blocks=[Block("paragraph", marker)])

    config = settings(workers=1)
    pipeline = Pipeline(config, engine=MockEngine(config, reader=reader))
    result = pipeline.run(images)
    assert len(result.pages) == len(images)
    assert [page.index for page in result.pages] == list(range(len(images)))


def test_normalisation_runs_over_the_whole_document(sample_image):
    text = "كتاب ايشان در سال ٢٠٢٥ چاپ شد ."
    config = settings()
    pipeline = Pipeline(config, engine=scripted([text, text])(config))
    result = pipeline.run([sample_image])
    assert "کتاب ایشان" in result.text
    assert "۲۰۲۵" in result.text
    assert " ." not in result.text


def test_normalisation_can_be_switched_off(sample_image):
    text = "كتاب ايشان"
    config = settings(normalize=False)
    result = Pipeline(config, engine=scripted([text, text])(config)).run([sample_image])
    assert "كتاب" in result.text


def test_the_report_records_applied_and_rejected_corrections(sample_image, tmp_path):
    from persian_ocr.report import write_reports

    def verifier(images, blocks, flags):
        return {
            "verdict": "corrected",
            "corrections": [
                {"block_index": 0, "original": "می‌رسذ", "corrected": "می‌رسد",
                 "reason": "dots", "confidence": 0.96},
                {"block_index": 0, "original": "نیچه", "corrected": "نیچهٔ بزرگِ آلمانی",
                 "reason": "context", "confidence": 0.99},
            ],
            "missing_text": [],
            "notes": "",
        }

    config = settings(verify=True, verify_rounds=1)
    pipeline = Pipeline(config, engine=scripted([MISREAD, MISREAD], verifier)(config))
    result = pipeline.run([sample_image])

    output = tmp_path / "out.txt"
    output.write_text(result.text, encoding="utf-8")
    written = write_reports(result, output)

    assert written["json"].exists() and written["markdown"].exists()
    report = written["report"]
    corrections = report["pages"][0]["corrections"]
    assert any(c["applied"] for c in corrections)
    assert any(not c["applied"] and c["rejected_because"] for c in corrections)
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert "اطمینانِ کلی" in markdown
