"""Run reports.

Two artefacts sit next to every output file:

* ``<name>.report.json`` — machine readable: per-page confidence, every
  correction (applied *and* rejected, with the reason), token usage, timings.
* ``<name>.report.md`` — a Persian summary a human can skim to find the pages
  worth eyeballing.

The rejected corrections matter as much as the applied ones: they are the
audit trail showing the verifier was not allowed to rewrite the book.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from .assemble import page_numbers_in
from .pipeline import RunResult

# Rough Claude API list prices, USD per million tokens, for the cost estimate.
PRICING = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = next((value for key, value in PRICING.items() if model.startswith(key)), None)
    if rates is None:
        return 0.0
    return input_tokens / 1e6 * rates[0] + output_tokens / 1e6 * rates[1]


def build_report(result: RunResult, output_path: Path) -> Dict:
    settings = result.settings
    usage = result.stats.get("usage", {})
    model = result.stats.get("model", "")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "output": str(output_path),
        "engine": result.stats.get("engine"),
        "model": model,
        "overall_confidence": round(result.confidence, 4),
        "statistics": {
            key: value
            for key, value in result.stats.items()
            if key not in {"usage", "normalisation", "cache"}
        },
        "normalisation": result.stats.get("normalisation", {}),
        "usage": {
            **usage,
            "estimated_cost_usd": round(
                estimate_cost(model, usage.get("input_tokens", 0), usage.get("output_tokens", 0)), 4
            ),
        },
        "cache": result.stats.get("cache", {}),
        "warnings": result.warnings,
        "settings": {
            "passes": settings.passes if settings else None,
            "verify": settings.verify if settings else None,
            "verify_rounds": settings.verify_rounds if settings else None,
            "dpi": settings.dpi if settings else None,
            "tile": settings.tile if settings else None,
            "normalize": settings.normalize if settings else None,
        },
        "pages": [
            {
                "index": page.index + 1,
                "source": page.label,
                "printed_page_numbers": page_numbers_in(page.blocks) or (
                    [page.page_number] if page.page_number else []
                ),
                "confidence": round(page.confidence, 4),
                "cross_pass_agreement": round(page.agreement, 4),
                "legibility": page.legibility,
                "words": len(page.text.split()),
                "seconds": page.usage.get("seconds"),
                "notes": page.notes,
                "open_flags": page.flags,
                "ignored_overlays": page.ignored_overlays,
                "corrections": page.corrections,
            }
            for page in result.pages
        ],
    }


def _bar(value: float, width: int = 20) -> str:
    filled = int(round(max(0.0, min(1.0, value)) * width))
    return "█" * filled + "░" * (width - filled)


def render_markdown(report: Dict) -> str:
    """A short Persian summary of the run."""
    lines: List[str] = []
    add = lines.append

    add("# گزارشِ تبدیلِ متن")
    add("")
    add(f"- تاریخ: {report['generated_at']}")
    add(f"- موتور: `{report.get('engine')}` — مدل: `{report.get('model')}`")
    add(f"- خروجی: `{report['output']}`")
    statistics = report.get("statistics", {})
    add(f"- صفحه‌ها: {statistics.get('pages', 0)} — واژه‌ها: {statistics.get('words', 0)} — نویسه‌ها: {statistics.get('characters', 0)}")
    add(f"- زمانِ اجرا: {statistics.get('seconds', 0)} ثانیه")
    usage = report.get("usage", {})
    if usage.get("requests"):
        add(
            f"- درخواست‌ها: {usage.get('requests', 0)} — توکن ورودی: {usage.get('input_tokens', 0):,} — "
            f"توکن خروجی: {usage.get('output_tokens', 0):,} — هزینه‌ی تقریبی: ${usage.get('estimated_cost_usd', 0)}"
        )
    add("")
    confidence = report.get("overall_confidence", 0.0)
    add(f"## اطمینانِ کلی: {confidence * 100:.1f}٪  `{_bar(confidence)}`")
    add("")

    if report.get("warnings"):
        add("### هشدارها")
        for warning in report["warnings"]:
            add(f"- {warning}")
        add("")

    add("## صفحه‌ها")
    add("")
    add("| # | منبع | شماره‌ی چاپی | اطمینان | همخوانیِ پاس‌ها | اصلاح‌شده | نکته‌های باز |")
    add("|---|------|--------------|---------|------------------|-----------|---------------|")
    for page in report.get("pages", []):
        applied = sum(1 for c in page.get("corrections", []) if c.get("applied"))
        add(
            f"| {page['index']} | {page['source']} | {'، '.join(page.get('printed_page_numbers') or []) or '—'} | "
            f"{page['confidence'] * 100:.1f}٪ | {page['cross_pass_agreement'] * 100:.1f}٪ | "
            f"{applied} | {len(page.get('open_flags', []))} |"
        )
    add("")

    flagged = [p for p in report.get("pages", []) if p["confidence"] < 0.9 or p.get("open_flags")]
    if flagged:
        add("## صفحه‌هایی که ارزشِ یک نگاهِ دوباره دارند")
        add("")
        for page in flagged:
            add(f"### صفحه‌ی {page['index']} ({page['source']}) — اطمینان {page['confidence'] * 100:.1f}٪")
            for flag in page.get("open_flags", [])[:12]:
                add(f"- {flag}")
            add("")

    corrections = [
        (page["index"], correction)
        for page in report.get("pages", [])
        for correction in page.get("corrections", [])
    ]
    applied = [(index, c) for index, c in corrections if c.get("applied")]
    rejected = [(index, c) for index, c in corrections if not c.get("applied")]

    if applied:
        add("## اصلاح‌هایی که اعمال شد")
        add("")
        add("| صفحه | نادرست | درست | دلیل | اطمینان |")
        add("|------|--------|------|------|---------|")
        for index, correction in applied[:200]:
            add(
                f"| {index} | `{correction['original']}` | `{correction['corrected']}` | "
                f"{correction['reason']} | {correction['confidence']} |"
            )
        add("")

    if rejected:
        add("## پیشنهادهایی که رد شد (برای شفافیت)")
        add("")
        add("| صفحه | پیشنهاد | چرا رد شد |")
        add("|------|---------|-----------|")
        for index, correction in rejected[:100]:
            add(
                f"| {index} | `{correction['original']}` ← `{correction['corrected']}` | "
                f"{correction.get('rejected_because')} |"
            )
        add("")

    normalisation = report.get("normalisation") or {}
    if normalisation:
        add("## یکدست‌سازیِ نویسه‌ها")
        add("")
        for name, count in normalisation.items():
            add(f"- {name}: {count}")
        add("")

    return "\n".join(lines) + "\n"


def write_reports(result: RunResult, output_path: Path) -> Dict[str, Path]:
    report = build_report(result, output_path)
    json_path = output_path.with_suffix(".report.json")
    markdown_path = output_path.with_suffix(".report.md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path, "report": report}
