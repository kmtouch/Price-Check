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
