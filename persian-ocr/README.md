<div dir="rtl">

# persian-ocr — تبدیلِ دقیقِ PDF و تصویرِ فارسی به متن

ابزاری برای تبدیلِ صفحه‌های اسکن‌شده، عکس‌گرفته‌شده یا اسکرین‌شاتِ متنِ فارسی
به یک فایلِ TXT تمیز — با **وارسیِ خودکارِ نتیجه**: آنچه خوانده شده دوباره در
برابرِ خودِ تصویر سنجیده می‌شود و هر جا که با تصویر نخواند، اصلاح می‌گردد.

## چرا این روش

خواندنِ متنِ کتابیِ فارسی برای OCRهای کلاسیک سخت است: خطِ فارسی پیوسته است،
شکلِ حرف‌ها با جایگاه‌شان عوض می‌شود، و آنچه معنا را می‌سازد — نقطه‌ها،
نیم‌فاصله، کسره‌ی اضافه، گیومه و شماره‌ی پانوشت — همان چیزی است که اول از همه
گم می‌شود. اینجا خواندنِ صفحه به یک مدلِ بینایی سپرده شده است، و مهم‌تر از آن،
هیچ نتیجه‌ای بدونِ وارسی پذیرفته نمی‌شود.

## نصب

```bash
cd persian-ocr
pip install -e .
export ANTHROPIC_API_KEY=...        # یا: ant auth login
persian-ocr doctor                  # بررسیِ نصب و کلید
```

## استفاده

```bash
# یک کتابِ اسکن‌شده
persian-ocr convert book.pdf -o book.txt

# چند تصویر (به ترتیبِ طبیعیِ نام)
persian-ocr convert scans/ -o book.txt

# فقط صفحه‌های ۱ تا ۲۰
persian-ocr convert book.pdf --pages 1-20 -o part1.txt

# محیطِ گرافیکی در مرورگر
persian-ocr serve --open
```

خروجی سه فایل است: `book.txt`، `book.report.md` (خلاصه‌ی فارسی) و
`book.report.json` (گزارشِ کاملِ ماشین‌خوان).

## نمونه‌ی گزارش

```
✓ wrote book.txt  (12,480 words, 34 page(s))
  overall confidence: 98.6%
  verification corrected 23 span(s)
  ⚠ 2 page(s) below 90% confidence: 17, 31
  report: book.report.md
```

هر اصلاحی که اعمال شده و — مهم‌تر — هر پیشنهادی که **رد شده** و دلیلِ ردّش، در
گزارش می‌آید. یعنی همیشه می‌دانید ابزار چه چیزی را دست زده است.

</div>

---

## What it does

Converts scanned PDFs, photos and screenshots of Persian text into clean UTF-8
plain text, and **verifies its own output**: the transcription is read back
against the page image and anything that does not match the pixels is
corrected.

## The pipeline

```
ingest ─► condition ─► tile ─► N OCR passes ─► consensus
                                                  │
        report ◄── assemble ◄── normalise ◄── verify against the image
                                                  ▲
                              rules + vocabulary screening
```

| Stage | What happens | Why |
|---|---|---|
| **ingest** | PDFs rasterised with PyMuPDF at 300 dpi; images loaded directly; multi-page TIFF and directories handled | one code path for every input |
| **condition** | the paper region is found inside app chrome and cropped; skew is measured by projection-profile contrast and corrected; contrast stretch + mild unsharp mask | screenshots of PDF readers carry toolbars, and heavy sharpening merges the dots of پ/ث |
| **tile** | tall pages are cut into overlapping near-square slices | the API downsamples anything past ~1568px, which is exactly where Persian diacritics live; the overlap guarantees a line clipped by one cut is intact in its neighbour |
| **OCR passes** | each slice is read twice (default) with different framings | two independently framed readings make uncorrelated mistakes, so disagreement localises the risk |
| **consensus** | word-level alignment and majority vote; contested spans recorded | agreement is the strongest cheap confidence signal there is |
| **checks** | balanced « », leaked UI chrome, mixed digit families, doubled words, footnote ordering, vocabulary screening | finds *where to look*, deterministically and for free |
| **verify** | the page's slices plus the assembled text plus the flags go back to the model, which reports what the page actually says | the only check that can settle a reading is the image itself |
| **vetting** | every proposed correction must quote a span that exists, clear a confidence floor, and stay close to the original | stops a "helpful" model from rewriting the book |
| **normalise** | Unicode form, Arabic look-alikes, digit families, punctuation spacing, half-spaces | encoding hygiene, never authorial style (see below) |
| **assemble** | tile seams spliced, page-break paragraphs rejoined, footnotes and page numbers placed | a book, not a pile of fragments |
| **report** | per-page confidence, applied corrections, **rejected** corrections with reasons, token usage and cost | an audit trail, not a black box |

## Faithfulness rules

The tool refuses to improve the text. Concretely:

* **The author's orthography survives.** The explicit dash separators in
  `برادرـ ام` and `دادـ وـ دهش` are the author's own convention, so tatweel is
  never stripped by default; printed ezafe kasras, tashdids and unusual
  spellings are transcribed as printed.
* **Half-spaces follow the document, not a style guide.** The normaliser
  measures how *this* document spells `می‌رود` / `کتاب‌ها` / `بزرگ‌تر` and only
  fixes places where the document contradicts itself. If a book is genuinely
  split between both spellings, nothing is touched. `--no-normalize` disables
  even that.
* **Latin context is left alone.** A German title keeps its own comma and its
  own digits: `Dämmerung, 1889` does not become `Dämmerung، ۱۸۸۹`.
* **Unreadable is unreadable.** A span hidden behind a watermark or a floating
  button is transcribed as `⟨؟⟩` and reported, never guessed.
* **Corrections are bounded.** A proposed fix that rewrites more than 40% of a
  span, changes its length by more than 2.5×, quotes text that is not in the
  document, or falls below the confidence floor is rejected and logged.

## Commands

```bash
persian-ocr convert  INPUTS... -o out.txt   # the main job
persian-ocr verify   out.txt --images page*.jpg   # re-check an existing transcription
persian-ocr benchmark out.txt --reference truth.txt   # CER/WER against ground truth
persian-ocr doctor                          # check the installation
persian-ocr serve --open                    # local browser UI
```

### Options worth knowing

| Flag | Effect |
|---|---|
| `--passes N` | independent readings per slice (default 2; 3 gives a real majority vote) |
| `--no-verify` | skip the re-read stage — faster and cheaper, and noticeably less accurate |
| `--verify-rounds N` | how many correction rounds to run (default 2, stops early when clean) |
| `--min-confidence` | the floor a correction must clear to be applied (default 0.75) |
| `--dpi` | PDF rasterisation resolution (default 300; raise for small print) |
| `--no-tile` | send whole pages instead of overlapping slices |
| `--dictionary PATH` | extra word list (plain text or hunspell `.dic`), repeatable |
| `--pages 1-20,25` | page selection for a single PDF |
| `--workers N` | pages processed in parallel (default 4) |
| `--engine tesseract` | offline fallback; needs `tesseract-ocr-fas`, and cannot verify |
| `--prefer-text-layer` | if the PDF already has selectable text, extract that instead |

Runs are cached on the image bytes, so re-running after changing output options
costs nothing, and an interrupted job resumes where it stopped.

## Cost and speed

One page ≈ 2 slices × 2 passes + 1 verification ≈ 5 requests. With
`claude-opus-5` that is roughly **$0.03–0.06 per page**; the exact figure for
every run is in the report. `--passes 1 --no-verify` cuts it to about a fifth,
and `--model claude-sonnet-5` roughly halves the rest — both trade accuracy for
price, which is why neither is the default.

## Measuring accuracy on your own material

```bash
persian-ocr convert samples/images/page-01.jpg -o /tmp/page-01.txt
persian-ocr benchmark /tmp/page-01.txt --reference samples/reference/page-01.txt
```

`samples/` holds three hard pages — a watermarked book read inside a PDF app,
toolbars and all — with hand-made reference transcriptions. `benchmark` folds
half-spaces, diacritics and digit families before comparing, so it scores
reading accuracy rather than encoding choices; `--strict` compares literally.

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q          # 131 tests, no network needed
```

The test suite runs the whole pipeline against a real sample page with a
scripted engine, so consensus, verification, vetting, assembly and reporting
are all exercised offline.

## Requirements

Python 3.9+, `anthropic`, `pillow`, `pymupdf`. Credentials via
`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or an `ant auth login` profile.
