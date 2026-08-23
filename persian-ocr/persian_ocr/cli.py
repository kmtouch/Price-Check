"""Command line interface.

    persian-ocr convert  book.pdf -o book.txt      # the main job
    persian-ocr verify   book.txt --images page*.jpg
    persian-ocr benchmark book.txt --reference truth.txt
    persian-ocr doctor
    persian-ocr serve
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__
from .config import DEFAULT_MODEL, DEFAULT_VERIFY_MODEL, Settings
from .engines import available_engines


def _progress_printer(quiet: bool):
    def write(message: str) -> None:
        if not quiet:
            print(f"  … {message}", file=sys.stderr, flush=True)

    return write


def _add_engine_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("engine")
    group.add_argument("--engine", default="auto", choices=available_engines(),
                       help="OCR engine (default: auto — an API key if set, else the "
                            "signed-in `claude` CLI, else tesseract)")
    group.add_argument("--model", default=DEFAULT_MODEL, help=f"vision model (default: {DEFAULT_MODEL})")
    group.add_argument("--verify-model", default=DEFAULT_VERIFY_MODEL,
                       help=f"model used for verification (default: {DEFAULT_VERIFY_MODEL})")
    group.add_argument("--api-key", default=None, help="Anthropic API key (else ANTHROPIC_API_KEY)")
    group.add_argument("--base-url", default=None, help="override the API base URL")
    group.add_argument("--passes", type=int, default=2,
                       help="independent OCR passes per tile; 2+ enables cross-checking (default: 2)")
    group.add_argument("--ocr-effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    group.add_argument("--verify-effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    group.add_argument("--max-tokens", type=int, default=16000)
    group.add_argument("--no-server-fallbacks", action="store_true",
                       help="do not let the API route a refusal to a fallback model")


def _add_image_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("image handling")
    group.add_argument("--dpi", type=int, default=300, help="PDF rasterisation resolution (default: 300)")
    group.add_argument("--max-edge", type=int, default=1568, help="longest edge sent to the API")
    group.add_argument("--no-tile", action="store_true", help="send whole pages instead of overlapping slices")
    group.add_argument("--tile-overlap", type=float, default=0.14)
    group.add_argument("--no-deskew", action="store_true")
    group.add_argument("--no-enhance", action="store_true")
    group.add_argument("--no-autocrop", action="store_true",
                       help="keep the surrounding app chrome instead of cropping to the page")


def _add_text_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("verification and text")
    group.add_argument("--no-verify", action="store_true", help="skip the re-read-against-the-image stage")
    group.add_argument("--verify-rounds", type=int, default=2)
    group.add_argument("--min-confidence", type=float, default=0.75,
                       help="reject corrections the verifier is less sure of (default: 0.75)")
    group.add_argument("--max-drift", type=float, default=0.4,
                       help="reject corrections that rewrite more than this fraction of a span")
    group.add_argument("--max-changed-words", type=int, default=2,
                       help="reject a correction touching more whole words than this (default: 2)")
    group.add_argument("--dictionary", action="append", default=[], metavar="PATH",
                       help="extra word list (plain text or hunspell .dic); repeatable")
    group.add_argument("--no-normalize", action="store_true", help="keep the raw characters as read")
    group.add_argument("--latin-digits", action="store_true", help="do not convert digits to Persian forms")
    group.add_argument("--latin-punctuation", action="store_true", help="keep , ; ? instead of ، ؛ ؟")
    group.add_argument("--no-page-numbers", action="store_true", help="drop printed page numbers from the output")
    group.add_argument("--no-join-pages", action="store_true",
                       help="do not rejoin a paragraph split across a page break")


def _settings_from_args(args: argparse.Namespace) -> Settings:
    return Settings(
        engine=args.engine,
        model=args.model,
        verify_model=args.verify_model,
        api_key=args.api_key,
        base_url=args.base_url,
        passes=max(1, args.passes),
        ocr_effort=args.ocr_effort,
        verify_effort=args.verify_effort,
        max_tokens=args.max_tokens,
        server_fallbacks=not args.no_server_fallbacks,
        dpi=args.dpi,
        max_edge=args.max_edge,
        tile=not args.no_tile,
        tile_overlap=args.tile_overlap,
        deskew=not args.no_deskew,
        enhance=not args.no_enhance,
        autocrop=not args.no_autocrop,
        verify=not args.no_verify,
        verify_rounds=args.verify_rounds,
        min_correction_confidence=args.min_confidence,
        max_correction_drift=args.max_drift,
        max_changed_words=args.max_changed_words,
        lexicon_paths=tuple(Path(p) for p in args.dictionary),
        normalize=not args.no_normalize,
        persian_digits=not args.latin_digits,
        persian_punctuation=not args.latin_punctuation,
        keep_page_numbers=not args.no_page_numbers,
        join_pages=not args.no_join_pages,
        workers=args.workers,
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        use_cache=not args.no_cache,
        quiet=args.quiet,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="persian-ocr",
        description="Convert scanned Persian PDFs and images into verified plain text.",
    )
    parser.add_argument("--version", action="version", version=f"persian-ocr {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- convert -----------------------------------------------------------
    convert = subparsers.add_parser("convert", help="convert PDFs/images to text")
    convert.add_argument("inputs", nargs="+", help="PDF, image, directory or glob")
    convert.add_argument("-o", "--output", default=None, help="output .txt path (default: alongside the input)")
    convert.add_argument("--pages", default=None, metavar="SPEC",
                         help="page selection for a single PDF, e.g. 1-5,9")
    convert.add_argument("--workers", type=int, default=4, help="pages processed in parallel (default: 4)")
    convert.add_argument("--cache-dir", default=None, help="cache directory (default: <output>.cache)")
    convert.add_argument("--no-cache", action="store_true")
    convert.add_argument("--no-report", action="store_true", help="do not write the .report.json/.md files")
    convert.add_argument("--json", action="store_true", help="print the report as JSON on stdout")
    convert.add_argument("--quiet", "-q", action="store_true")
    convert.add_argument("--prefer-text-layer", action="store_true",
                         help="if the PDF already has selectable text, extract that instead of running OCR")
    _add_engine_arguments(convert)
    _add_image_arguments(convert)
    _add_text_arguments(convert)

    # -- verify ------------------------------------------------------------
    verify = subparsers.add_parser("verify", help="re-check an existing .txt against its page images")
    verify.add_argument("text", help="the transcription to check")
    verify.add_argument("--images", nargs="+", required=True, help="the source pages, in order")
    verify.add_argument("-o", "--output", default=None, help="where to write the corrected text")
    verify.add_argument("--workers", type=int, default=4)
    verify.add_argument("--cache-dir", default=None)
    verify.add_argument("--no-cache", action="store_true")
    verify.add_argument("--quiet", "-q", action="store_true")
    _add_engine_arguments(verify)
    _add_image_arguments(verify)
    _add_text_arguments(verify)

    # -- benchmark ---------------------------------------------------------
    benchmark = subparsers.add_parser("benchmark", help="score a transcription against a reference")
    benchmark.add_argument("hypothesis")
    benchmark.add_argument("--reference", required=True)
    benchmark.add_argument("--strict", action="store_true",
                           help="compare literally, without folding half-spaces and diacritics")
    benchmark.add_argument("--json", action="store_true")
    benchmark.add_argument("--show-diff", type=int, default=15, metavar="N")

    # -- doctor ------------------------------------------------------------
    subparsers.add_parser("doctor", help="check the installation and credentials")

    # -- serve -------------------------------------------------------------
    serve = subparsers.add_parser("serve", help="run the local browser interface")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--open", action="store_true", help="open a browser window")
    serve.add_argument("--workers", type=int, default=4)
    serve.add_argument("--cache-dir", default=None)
    serve.add_argument("--no-cache", action="store_true")
    serve.add_argument("--quiet", "-q", action="store_true")
    _add_engine_arguments(serve)
    _add_image_arguments(serve)
    _add_text_arguments(serve)

    return parser


# -- commands -------------------------------------------------------------
def command_convert(args: argparse.Namespace) -> int:
    from .ingest import IngestError, expand_inputs, extract_pdf_text, parse_page_selection, pdf_has_text_layer
    from .pipeline import Pipeline
    from .report import write_reports

    try:
        paths = expand_inputs(args.inputs)
    except IngestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    output = Path(args.output) if args.output else paths[0].with_suffix(".txt")
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.prefer_text_layer and len(paths) == 1 and paths[0].suffix.lower() == ".pdf":
        if pdf_has_text_layer(paths[0]):
            text = extract_pdf_text(paths[0])
            output.write_text(text, encoding="utf-8")
            print(f"extracted the existing PDF text layer → {output}")
            return 0

    for path in paths:
        if path.suffix.lower() == ".pdf" and pdf_has_text_layer(path):
            print(
                f"note: {path.name} already contains selectable text. OCR still runs; "
                "pass --prefer-text-layer to extract that instead (faster and exact).",
                file=sys.stderr,
            )

    settings = _settings_from_args(args)
    if settings.cache_dir is None and settings.use_cache:
        settings = settings.with_(cache_dir=output.with_suffix(".cache"))

    selection = parse_page_selection(args.pages) if args.pages else None

    pipeline = Pipeline(settings, progress=_progress_printer(args.quiet))
    try:
        result = pipeline.run(paths, selection)
    except Exception as exc:  # noqa: BLE001 - the CLI is the top level
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output.write_text(result.text, encoding="utf-8")

    report = None
    if not args.no_report:
        written = write_reports(result, output)
        report = written["report"]

    if args.json:
        print(json.dumps(report or {}, ensure_ascii=False, indent=2))
    elif not args.quiet:
        _print_summary(result, output, report)
    return 0


def _print_summary(result, output: Path, report: Optional[dict]) -> None:
    stats = result.stats
    print()
    print(f"✓ wrote {output}  ({stats.get('words', 0):,} words, {stats.get('pages', 0)} page(s))")
    print(f"  overall confidence: {result.confidence * 100:.1f}%")
    applied = sum(
        1 for page in result.pages for correction in page.corrections if correction.get("applied")
    )
    if applied:
        print(f"  verification corrected {applied} span(s)")
    usage = stats.get("usage", {})
    if usage.get("requests"):
        print(
            f"  {usage['requests']} API request(s), "
            f"{usage.get('input_tokens', 0):,} in / {usage.get('output_tokens', 0):,} out"
        )
    weak = result.low_confidence_pages()
    if weak:
        print(f"  ⚠ {len(weak)} page(s) below 90% confidence: " +
              ", ".join(str(page.index + 1) for page in weak[:12]))
    for warning in result.warnings:
        print(f"  ⚠ {warning}")
    if report:
        print(f"  report: {output.with_suffix('.report.md')}")


def command_verify(args: argparse.Namespace) -> int:
    """Re-check an existing transcription against its page images."""
    from .assemble import PageResult, render_document
    from .engines.base import Block
    from .ingest import IngestError, expand_inputs, load_pages
    from .lexicon import Lexicon
    from .pipeline import Pipeline, RunResult
    from .preprocess import condition, tile_page
    from .report import write_reports
    from .verify import confidence_score, run_checks

    text_path = Path(args.text)
    if not text_path.exists():
        print(f"error: {text_path} not found", file=sys.stderr)
        return 2
    try:
        image_paths = expand_inputs(args.images)
    except IngestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    settings = _settings_from_args(args).with_(verify=True)
    output = Path(args.output) if args.output else text_path.with_name(text_path.stem + ".verified.txt")
    if settings.cache_dir is None and settings.use_cache:
        settings = settings.with_(cache_dir=output.with_suffix(".cache"))

    pipeline = Pipeline(settings, progress=_progress_printer(args.quiet))
    pages_of_text = text_path.read_text(encoding="utf-8").split("\f")
    source_pages = load_pages(image_paths, dpi=settings.dpi)
    if len(pages_of_text) != len(source_pages):
        # No form feeds in the file: treat the whole text as one page per image
        # only when the counts happen to line up, else split by blank lines.
        chunks = [chunk for chunk in text_path.read_text(encoding="utf-8").split("\n\n") if chunk.strip()]
        per_page = max(1, len(chunks) // max(1, len(source_pages)))
        pages_of_text = [
            "\n\n".join(chunks[i : i + per_page]) for i in range(0, len(chunks), per_page)
        ][: len(source_pages)]
        while len(pages_of_text) < len(source_pages):
            pages_of_text.append("")

    lexicon = Lexicon(tuple(settings.lexicon_paths), document_text=text_path.read_text(encoding="utf-8"))
    results: List[PageResult] = []
    for page, page_text in zip(source_pages, pages_of_text):
        blocks = [Block("paragraph", chunk.strip()) for chunk in page_text.split("\n\n") if chunk.strip()]
        result = PageResult(index=page.index, label=page.label, blocks=blocks)
        image, _info = condition(
            page.image,
            do_autocrop=settings.autocrop,
            do_deskew=settings.deskew,
            do_enhance=settings.enhance,
        )
        tiles = tile_page(image, max_edge=settings.max_edge, overlap=settings.tile_overlap,
                          enabled=settings.tile)
        checks = run_checks(result.blocks, lexicon, [])
        result.flags = checks.flags
        corrections = pipeline._verify_page(page, tiles, result, checks, lexicon)
        result.corrections = [c.to_dict() for c in corrections]
        final = run_checks(result.blocks, lexicon, [])
        result.flags = final.flags
        result.confidence = confidence_score(
            agreement=1.0,
            lexicon_coverage=final.lexicon_coverage,
            structural_problems=len(final.structural),
            unresolved_flags=len(final.vocabulary),
            words=len(result.text.split()),
        )
        results.append(result)

    text = render_document(results, page_marks="number" if settings.keep_page_numbers else "none",
                           join_pages=settings.join_pages)
    output.write_text(text, encoding="utf-8")
    run = RunResult(text=text, pages=results, stats={"pages": len(results), "engine": pipeline.engine.name,
                                                     "model": settings.verify_model,
                                                     "usage": pipeline.usage},
                    settings=settings)
    write_reports(run, output)
    if not args.quiet:
        applied = sum(1 for page in results for c in page.corrections if c.get("applied"))
        print(f"✓ wrote {output} — {applied} correction(s) applied")
    return 0


def command_benchmark(args: argparse.Namespace) -> int:
    from .metrics import compare, diff_words

    hypothesis = Path(args.hypothesis).read_text(encoding="utf-8")
    reference = Path(args.reference).read_text(encoding="utf-8")
    accuracy = compare(hypothesis, reference, fold=not args.strict)

    if args.json:
        print(json.dumps(accuracy.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"character accuracy: {accuracy.character_accuracy * 100:.2f}%  (CER {accuracy.cer * 100:.2f}%)")
    print(f"word accuracy:      {accuracy.word_accuracy * 100:.2f}%  (WER {accuracy.wer * 100:.2f}%)")
    print(f"reference size:     {accuracy.reference_chars:,} chars / {accuracy.reference_words:,} words")
    if args.show_diff:
        differences = diff_words(hypothesis, reference, limit=args.show_diff)
        if differences:
            print("\ndifferences:")
            for line in differences:
                print(f"  {line}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    import shutil

    print(f"persian-ocr {__version__}")
    print(f"python      {sys.version.split()[0]}")

    ok = True

    def check(name: str, condition: bool, hint: str = "", required: bool = True) -> None:
        nonlocal ok
        mark = "✓" if condition else ("✗" if required else "-")
        print(f"  [{mark}] {name}" + ("" if condition or not hint else f" — {hint}"))
        if required:
            ok = ok and condition

    try:
        import PIL

        check(f"Pillow {PIL.__version__}", True)
    except ImportError:
        check("Pillow", False, "pip install pillow")
    try:
        import pymupdf

        check(f"PyMuPDF {pymupdf.__doc__.split()[1].rstrip(':')}", True)
    except Exception:
        check("PyMuPDF (PDF support)", False, "pip install pymupdf")
    try:
        import anthropic

        check(f"anthropic SDK {anthropic.__version__}", True)
    except ImportError:
        check("anthropic SDK", False, "pip install anthropic")

    import os

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    profile = Path.home() / ".config" / "anthropic"
    claude_cli = shutil.which(os.environ.get("PERSIAN_OCR_CLAUDE_BIN") or "claude")
    check("Anthropic API key (optional)", has_key or profile.exists(),
          "not set — that is fine if the `claude` CLI below is available", required=False)
    check("claude CLI (works without an API key)", claude_cli is not None,
          "install Claude Code from https://claude.com/claude-code and sign in", required=False)
    check("tesseract (optional offline engine)", shutil.which("tesseract") is not None,
          "sudo apt install tesseract-ocr tesseract-ocr-fas", required=False)

    from .engines import EngineError, resolve_engine

    try:
        print(f"  [✓] engine `auto` resolves to `{resolve_engine('auto')}`")
    except EngineError as exc:
        ok = False
        print(f"  [✗] no usable engine — {exc}")

    from .lexicon import Lexicon

    lexicon = Lexicon()
    check(f"bundled Persian word list ({len(lexicon.words):,} entries)", len(lexicon.words) > 500)

    print("\nready" if ok else "\nsome checks failed — see the hints above")
    return 0 if ok else 1


def command_serve(args: argparse.Namespace) -> int:
    from .webui import serve

    settings = _settings_from_args(args)
    serve(settings, host=args.host, port=args.port, open_browser=args.open)
    return 0


COMMANDS = {
    "convert": command_convert,
    "verify": command_verify,
    "benchmark": command_benchmark,
    "doctor": command_doctor,
    "serve": command_serve,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
