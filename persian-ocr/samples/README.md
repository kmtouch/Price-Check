# نمونه‌ها / Samples

`images/` holds three screenshots of a Persian book read in a PDF viewer — the
hard case this tool was built for: no text layer, a diagonal watermark across
the page, and the reader's own toolbars above and below the paper.

`reference/` holds the matching transcriptions, made by hand and reviewed, and
used as ground truth by `persian-ocr benchmark`:

```bash
persian-ocr convert samples/images/page-01.jpg -o /tmp/page-01.txt
persian-ocr benchmark /tmp/page-01.txt --reference samples/reference/page-01.txt
```

Conventions in the reference files:

* `⟨؟⟩` marks characters that are genuinely unreadable in the source — on
  `page-03` the reader's floating button covers part of two words. The tool
  uses the same marker, so a run that reports them agrees with the reference.
* The author's own orthography is preserved exactly, including the explicit
  `ـ` separators (`برادرـ ام`, `دادـ وـ دهش`) and the ezafe kasras. These are
  intentional and must survive a conversion.
* Page numbers printed on the page (`۴`, `۵`) are kept on their own line, which
  is what `--page-numbers` (the default) produces.

## `output/` — a worked example

Two runs over the three pages above, produced by the real pipeline with the
engine replaying a recorded reading instead of calling the API (the sandbox
this was built in had no API key). Everything after the reading — consensus,
checks, verification, vetting, normalisation, assembly, reporting — is the
actual code doing the actual work.

| File | What it shows |
|---|---|
| `nietzsche-3-pages.txt` | the converted text of all three pages |
| `nietzsche-3-pages.report.md` | the run report for a clean read |
| `demo-error-recovery.txt` | byte-identical to the file above |
| `demo-error-recovery.report.md` | the same run with six typical OCR faults injected into the reading |

The second run is the interesting one. Injected into the reading were three
dot confusions (`دستغیت`, `می‌گیرذ`, `زیباروبان`), a fourth on the next page
(`پرسنیده‌اند`), a leaked toolbar label (`Edit PDF`), and — from the verifier
— one suggestion that improves the *style* rather than matching the image
(`این گونه واژه‌ها و عبارت‌ها و جمله‌ها` → `این‌گونه واژگان و عبارات و جملات`).

The five reading faults were corrected; the style rewrite was refused, with the
reason recorded in the report. The output is byte-identical to the clean run.

Because the reading is replayed, the 100% benchmark score of this demo says
nothing about the tool's accuracy against the live API — it measures the rest
of the pipeline. Run it with your own key to get a real number.
