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
persian-ocr doctor                  # می‌گوید کدام موتور در دسترس است
```

**کلیدِ API لازم نیست.** اگر Claude Code را نصب دارید و در آن وارد شده‌اید،
ابزار خودش از همان نشست استفاده می‌کند و کار روی اشتراکِ موجودِ شما حساب
می‌شود:

| در دسترس | موتور | چه لازم دارد |
|---|---|---|
| `claude` نصب و لاگین شده | `claude-cli` | **هیچ کلیدی** — اشتراکِ Claude Code |
| `ANTHROPIC_API_KEY` تنظیم شده | `anthropic` | کلیدِ API |
| هیچ‌کدام، ولی `tesseract` هست | `tesseract` | آفلاین، رایگان، دقتِ به‌مراتب کمتر |

پیش‌فرض `--engine auto` است: هرکدام که باشد خودش انتخاب می‌کند و به شما
می‌گوید کدام را برداشته.

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
* **Corrections are bounded.** A proposed fix is rejected and logged if it
  quotes text that is not in the document, falls below the confidence floor,
  changes its span's length by more than 2.5×, rewrites more than 40% of it, or
  touches more than two whole words. That last rule is the one that matters:
  Persian synonyms share their stems, so a fluency rewrite
  (`واژه‌ها` → `واژگان`, `عبارت‌ها` → `عبارات`) looks similar character by
  character and only shows up when whole changed words are counted.

## Engines — and running without an API key

`--engine auto` (the default) picks whatever is available and tells you which
it chose:

| Engine | Needs | Notes |
|---|---|---|
| `claude-cli` | Claude Code installed and signed in — **no API key** | Drives `claude --print` with a Read-only tool grant and parses the JSON it returns. The work counts against the existing Claude Code subscription. |
| `anthropic` | `ANTHROPIC_API_KEY` | The HTTP API. Schema-constrained responses, parallel requests, lowest latency. |
| `tesseract` | `tesseract-ocr-fas` | Fully offline and free. Much weaker on book typography — it has no notion of the half-space and drops diacritics — and it cannot verify, so only the rule and vocabulary checks run. |

```bash
persian-ocr convert book.pdf -o book.txt                  # auto
persian-ocr convert book.pdf -o book.txt --engine claude-cli
```

The CLI engine is slower than the HTTP one (each page is a separate `claude`
invocation, roughly 40–90 seconds) and gets its JSON by instruction rather than
by schema constraint, so the engine repairs near-miss reply shapes instead of
throwing a page away. Everything downstream — consensus, checks, verification,
vetting, assembly, reporting — is identical.

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
| `--max-changed-words` | reject a correction touching more whole words than this (default 2) |
| `--dpi` | PDF rasterisation resolution (default 300; raise for small print) |
| `--no-tile` | send whole pages instead of overlapping slices |
| `--dictionary PATH` | extra word list (plain text or hunspell `.dic`), repeatable |
| `--pages 1-20,25` | page selection for a single PDF |
| `--workers N` | pages processed in parallel (default 4) |
| `--engine claude-cli` | use the signed-in Claude Code CLI instead of an API key |
| `--engine tesseract` | offline fallback; needs `tesseract-ocr-fas`, and cannot verify |
| `--prefer-text-layer` | if the PDF already has selectable text, extract that instead |
| `--strip-headers-footers` | drop a running header/footer/watermark line that repeats at the top or bottom of enough pages (see below) |

Runs are cached on the image bytes, so re-running after changing output options
costs nothing, and an interrupted job resumes where it stopped. Nothing limits
how many pages a single run can process — `--passes` controls how many times
*each* page is independently re-read for cross-checking, not how many pages
get converted.

### Stripping running headers, footers and watermarks

`--strip-headers-footers` looks for a line that shows up, worded identically,
as the first or last block of enough pages — a book title repeated at the top
of every page, a publisher line at the bottom, a page banner that only
differs by its own page number (digits are ignored when comparing, so a
changing page number doesn't defeat the match). That repetition is the
signal: a real paragraph that happens to open two pages with the same
sentence is left alone, because two is never enough to trigger it.

This is a second line of defence, not the first — the OCR prompt already
tells the model to leave application chrome and watermark text out of the
transcription entirely (`ignored_overlays` in the report). The flag catches
what gets through anyway, plus genuine printed running headers/footers, which
the prompt does not touch because they are real page content, not noise; only
remove them if you actually don't want them in the output. Off by default.

## Cost and speed

One page ≈ 2 slices × 2 passes + 1 verification ≈ 5 requests. With
`claude-opus-5` that is roughly **$0.03–0.06 per page**; the exact figure for
every run is in the report. `--passes 1 --no-verify` cuts it to about a fifth,
and `--model claude-sonnet-5` roughly halves the rest — both trade accuracy for
price, which is why neither is the default.

## The `serve` HTTP API — for large batches and other clients

`persian-ocr serve` runs conversions as **background jobs**, not inside the
request: a 100-page document can easily take over an hour, and holding one
HTTP connection open that long is fragile — a phone locking its screen, a
laptop sleeping, or a flaky Wi-Fi hop all kill an in-flight request and lose
the whole run. `POST /convert` hands back a job id immediately; the job keeps
running on the server, and the caller polls for progress and, eventually, the
result. This is what the Android app and the built-in browser page both do.

```
POST /convert   multipart/form-data: files[], verify, normalize,
                page_numbers, strip_headers, passes
                → 202 {"job_id": "..."}

GET /jobs/<id>  → {"status": "queued"|"running"|"done"|"error",
                    "pages_total": int|null, "pages_done": int,
                    "log": [...], "result": {...}|null, "error": str|null}
```

A finished job's result stays available for 6 hours, so a client that lost
its connection mid-run can reconnect later and still collect the answer — the
Android app stores the job id and resumes polling automatically the next time
it opens.

## Measured on real pages

A live run through the CLI engine over the three sample pages — screenshots of
a watermarked book inside a PDF reader, toolbars and all:

| Run | Character accuracy | Word accuracy |
|---|---|---|
| whole pages, 2 passes, no tiling | 99.42% | 96.04% |
| one page, tiled, 2 passes + verification | **99.52%** | **98.19%** |

Measured with `persian-ocr benchmark` against the hand-made references in
`samples/reference/`. Several of the remaining word-level differences are
half-space judgement calls where the tool is arguably right and the reference
was normalised by hand — so treat the word figure as a floor.

`samples/output/page-01.live.*` is that run, checked in.

## A worked example

`samples/output/` holds a complete run over the three sample pages: the
converted text, the run report, and a second run with six typical OCR faults
injected into the reading. Five were reading errors and were corrected; the
sixth was a suggestion that improved the prose rather than matching the image,
and was refused:

```
## اصلاح‌هایی که اعمال شد
| صفحه | نادرست | درست | دلیل | اطمینان |
| 2 | `دستغیت` | `دستغیب` | the page shows the dotted form | 0.96 |
| 2 | ` Edit PDF` | `` | overlay — application toolbar, not part of the page | 0.98 |

## پیشنهادهایی که رد شد (برای شفافیت)
| 2 | `این گونه واژه‌ها…` ← `این‌گونه واژگان…` | changes 5 whole words — that is a rewrite, not a targeted fix |
```

The corrected output is byte-identical to the clean run. See
`samples/README.md` for the caveat on what that demo does and does not prove.

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
python -m pytest -q          # 181 tests, no network needed
```

The test suite runs the whole pipeline against a real sample page with a
scripted engine, so consensus, verification, vetting, assembly and reporting
are all exercised offline.

## Requirements

Python 3.10+ (the Anthropic SDK's own floor), `pillow`, `pymupdf`, and one of:

* **Claude Code**, installed and signed in — no API key, no extra billing;
* an Anthropic API key (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or an
  `ant auth login` profile) with the `anthropic` package;
* **Tesseract** with `tesseract-ocr-fas` for a fully offline, much less
  accurate run.

`persian-ocr doctor` reports which of these it can see.
