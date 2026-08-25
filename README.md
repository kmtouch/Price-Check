# Price-Check

This repository holds three independent projects:

## PriceWatcher (`app/`)

An Android app that tracks the price of products on the web and keeps a history
of what it finds. Built with Gradle; see `app/` and `.github/workflows/build.yml`.

## persian-ocr (`persian-ocr/`)

A Python tool that converts scanned Persian PDFs and images into verified plain
text: it reads each page with a vision model, cross-checks independent passes,
then re-reads its own output against the page image and corrects whatever does
not match. Works with an Anthropic API key, or with no key at all via a
signed-in Claude Code CLI. See [`persian-ocr/README.md`](persian-ocr/README.md).

```bash
cd persian-ocr && pip install -e .
persian-ocr convert book.pdf -o book.txt
persian-ocr serve --host 0.0.0.0     # local web UI, reachable from other devices
```

## Persian OCR — Android app (`persian-ocr-android/`)

A thin Android client for `persian-ocr serve` above: pick photos or a PDF on
the phone, upload to a server you run on a computer, get back verified text.
No API key lives in the app. See
[`persian-ocr-android/README.md`](persian-ocr-android/README.md). Built
automatically by `.github/workflows/persian-ocr-android.yml` on every push
that touches this directory — the debug APK is uploaded as a build artifact.
