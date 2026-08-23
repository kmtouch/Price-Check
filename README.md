# Price-Check

This repository holds two independent projects:

## PriceWatcher (`app/`)

An Android app that tracks the price of products on the web and keeps a history
of what it finds. Built with Gradle; see `app/` and `.github/workflows/build.yml`.

## persian-ocr (`persian-ocr/`)

A Python tool that converts scanned Persian PDFs and images into verified plain
text: it reads each page with a vision model, cross-checks independent passes,
then re-reads its own output against the page image and corrects whatever does
not match. See [`persian-ocr/README.md`](persian-ocr/README.md).

```bash
cd persian-ocr && pip install -e .
persian-ocr convert book.pdf -o book.txt
```
