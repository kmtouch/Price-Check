"""A small local web interface: drop files in, get text out.

Deliberately built on the standard library only — no Flask, no bundler, no
build step. It binds to localhost by default because it processes local files
and can spend money on API calls; it is a personal tool, not a service.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Tuple

from . import __version__
from .config import Settings
from .ingest import SUPPORTED_SUFFIXES

MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def parse_multipart(body: bytes, boundary: bytes) -> Tuple[List[Tuple[str, bytes]], Dict[str, str]]:
    """Minimal multipart/form-data parser (files and plain fields)."""
    files: List[Tuple[str, bytes]] = []
    fields: Dict[str, str] = {}
    delimiter = b"--" + boundary
    for part in body.split(delimiter):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_blob, _, content = part.partition(b"\r\n\r\n")
        if not _:
            continue
        headers = header_blob.decode("utf-8", "replace")
        disposition = next(
            (line for line in headers.split("\r\n") if line.lower().startswith("content-disposition")),
            "",
        )
        name_match = re.search(r'name="([^"]*)"', disposition)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        if not name_match:
            continue
        content = content.rstrip(b"\r\n")
        if filename_match and filename_match.group(1):
            files.append((Path(filename_match.group(1)).name, content))
        else:
            fields[name_match.group(1)] = content.decode("utf-8", "replace")
    return files, fields


PAGE = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>تبدیلِ تصویر و PDF فارسی به متن</title>
<style>
  :root {{
    --bg: #faf8f4; --panel: #fff; --ink: #201c18; --muted: #6c635a;
    --line: #e4ddd2; --accent: #8a5a2b; --ok: #2f7d4f; --warn: #b26a00;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #16130f; --panel: #201c18; --ink: #f2ece3; --muted: #a89c8d;
             --line: #362f27; --accent: #d59a5c; --ok: #6cc48c; --warn: #e0a355; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink);
         font-family: Vazirmatn, "Noto Naskh Arabic", Tahoma, system-ui, sans-serif; line-height: 1.8; }}
  .wrap {{ max-width: 60rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .25rem; }}
  p.sub {{ color: var(--muted); margin: 0 0 2rem; }}
  .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
           padding: 1.25rem; margin-bottom: 1.25rem; }}
  .drop {{ border: 2px dashed var(--line); border-radius: 12px; padding: 2.5rem 1rem;
           text-align: center; cursor: pointer; transition: .15s; }}
  .drop.hot {{ border-color: var(--accent); background: rgba(138,90,43,.06); }}
  .files {{ margin-top: .75rem; font-size: .9rem; color: var(--muted); }}
  .row {{ display: flex; flex-wrap: wrap; gap: 1.25rem; align-items: center; }}
  label.opt {{ display: flex; align-items: center; gap: .4rem; font-size: .95rem; }}
  button {{ font: inherit; background: var(--accent); color: #fff; border: 0; border-radius: 10px;
            padding: .6rem 1.4rem; cursor: pointer; }}
  button:disabled {{ opacity: .5; cursor: default; }}
  button.ghost {{ background: transparent; color: var(--accent); border: 1px solid var(--line); }}
  textarea {{ width: 100%; min-height: 24rem; border-radius: 10px; border: 1px solid var(--line);
              background: var(--bg); color: var(--ink); padding: 1rem; font-size: 1.05rem;
              line-height: 2.1; font-family: inherit; }}
  .stat {{ display: inline-block; margin-left: 1.5rem; font-size: .95rem; }}
  .stat b {{ color: var(--ok); }}
  .warn {{ color: var(--warn); }}
  .log {{ font-family: ui-monospace, monospace; font-size: .8rem; color: var(--muted);
          white-space: pre-wrap; max-height: 12rem; overflow: auto; direction: ltr; text-align: left; }}
  .hidden {{ display: none; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>تبدیلِ تصویر و PDF فارسی به متن</h1>
  <p class="sub">persian-ocr {version} — فایل‌ها روی همین رایانه پردازش می‌شوند؛ تنها تصویرِ صفحه‌ها برای خواندن به مدل فرستاده می‌شود.</p>

  <div class="card">
    <div class="drop" id="drop">
      <div>فایل‌های PDF یا تصویر را اینجا رها کنید یا کلیک کنید</div>
      <div class="files" id="filelist">هنوز فایلی انتخاب نشده است</div>
    </div>
    <input type="file" id="picker" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp" class="hidden">
    <div class="row" style="margin-top:1.25rem">
      <label class="opt"><input type="checkbox" id="verify" checked> وارسیِ خودکارِ نتیجه</label>
      <label class="opt"><input type="checkbox" id="normalize" checked> یکدست‌سازیِ نویسه‌های فارسی</label>
      <label class="opt"><input type="checkbox" id="pagenums" checked> نگه‌داشتنِ شماره‌ی صفحه</label>
      <label class="opt">پاس‌ها:
        <select id="passes"><option>1</option><option selected>2</option><option>3</option></select>
      </label>
      <button id="run" disabled>تبدیل کن</button>
    </div>
  </div>

  <div class="card hidden" id="result">
    <div class="row" style="justify-content:space-between; margin-bottom:1rem">
      <div id="stats"></div>
      <div class="row">
        <button class="ghost" id="copy">رونوشت</button>
        <button class="ghost" id="download">دریافتِ TXT</button>
      </div>
    </div>
    <textarea id="text" spellcheck="false"></textarea>
    <div class="log" id="log"></div>
  </div>
</div>
<script>
const picker = document.getElementById('picker');
const drop = document.getElementById('drop');
const runButton = document.getElementById('run');
let chosen = [];

function setFiles(list) {{
  chosen = Array.from(list);
  document.getElementById('filelist').textContent =
    chosen.length ? chosen.map(f => f.name).join('، ') : 'هنوز فایلی انتخاب نشده است';
  runButton.disabled = chosen.length === 0;
}}
drop.addEventListener('click', () => picker.click());
picker.addEventListener('change', e => setFiles(e.target.files));
['dragenter','dragover'].forEach(t => drop.addEventListener(t, e => {{
  e.preventDefault(); drop.classList.add('hot');
}}));
['dragleave','drop'].forEach(t => drop.addEventListener(t, e => {{
  e.preventDefault(); drop.classList.remove('hot');
}}));
drop.addEventListener('drop', e => setFiles(e.dataTransfer.files));

runButton.addEventListener('click', async () => {{
  runButton.disabled = true;
  const original = runButton.textContent;
  runButton.textContent = 'در حالِ خواندن…';
  const form = new FormData();
  chosen.forEach(file => form.append('files', file));
  form.append('verify', document.getElementById('verify').checked ? '1' : '0');
  form.append('normalize', document.getElementById('normalize').checked ? '1' : '0');
  form.append('page_numbers', document.getElementById('pagenums').checked ? '1' : '0');
  form.append('passes', document.getElementById('passes').value);
  try {{
    const response = await fetch('/convert', {{ method: 'POST', body: form }});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'خطا');
    document.getElementById('result').classList.remove('hidden');
    document.getElementById('text').value = data.text;
    const percent = (data.confidence * 100).toFixed(1);
    document.getElementById('stats').innerHTML =
      '<span class="stat">اطمینان: <b>' + percent + '٪</b></span>' +
      '<span class="stat">واژه‌ها: ' + data.words + '</span>' +
      '<span class="stat">صفحه‌ها: ' + data.pages + '</span>' +
      (data.corrections ? '<span class="stat">اصلاح‌ها: ' + data.corrections + '</span>' : '') +
      (data.low_confidence_pages.length
        ? '<span class="stat warn">صفحه‌های کم‌اطمینان: ' + data.low_confidence_pages.join('، ') + '</span>'
        : '');
    document.getElementById('log').textContent = data.log.join('\\n');
  }} catch (error) {{
    alert('خطا: ' + error.message);
  }} finally {{
    runButton.disabled = false;
    runButton.textContent = original;
  }}
}});

document.getElementById('copy').addEventListener('click', () => {{
  navigator.clipboard.writeText(document.getElementById('text').value);
}});
document.getElementById('download').addEventListener('click', () => {{
  const blob = new Blob([document.getElementById('text').value], {{ type: 'text/plain;charset=utf-8' }});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'output.txt';
  link.click();
  URL.revokeObjectURL(link.href);
}});
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    settings: Settings = Settings()
    server_version = f"persian-ocr/{__version__}"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        if not self.settings.quiet:
            super().log_message(format, *args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.format(version=__version__).encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/convert":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return

        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_UPLOAD_BYTES:
            self._error(413, "the upload is too large")
            return
        if "boundary=" not in content_type:
            self._error(400, "expected a multipart upload")
            return

        boundary = content_type.split("boundary=")[1].strip().strip('"').encode()
        files, fields = parse_multipart(self.rfile.read(length), boundary)
        files = [(name, data) for name, data in files if Path(name).suffix.lower() in SUPPORTED_SUFFIXES]
        if not files:
            self._error(400, "no supported files were uploaded")
            return

        log: List[str] = []
        workdir = Path(tempfile.mkdtemp(prefix="persian-ocr-"))
        try:
            paths = []
            for name, data in files:
                path = workdir / name
                path.write_bytes(data)
                paths.append(path)

            settings = self.settings.with_(
                verify=fields.get("verify", "1") == "1",
                normalize=fields.get("normalize", "1") == "1",
                keep_page_numbers=fields.get("page_numbers", "1") == "1",
                passes=max(1, min(3, int(fields.get("passes", "2") or 2))),
                cache_dir=workdir / "cache",
            )

            from .pipeline import Pipeline

            pipeline = Pipeline(settings, progress=log.append)
            result = pipeline.run(paths)
            corrections = sum(
                1 for page in result.pages for c in page.corrections if c.get("applied")
            )
            payload = {
                "text": result.text,
                "confidence": round(result.confidence, 4),
                "words": result.stats.get("words", 0),
                "pages": result.stats.get("pages", 0),
                "corrections": corrections,
                "low_confidence_pages": [p.index + 1 for p in result.low_confidence_pages()],
                "log": log + result.warnings,
            }
            self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")
        except Exception as exc:  # noqa: BLE001
            self._error(500, str(exc))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _error(self, status: int, message: str) -> None:
        self._send(
            status,
            json.dumps({"error": html.escape(message)}, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )


def serve(settings: Settings, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    Handler.settings = settings
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"persian-ocr is listening on {url}  (ctrl-c to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
