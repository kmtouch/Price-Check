"""A small local web interface: drop files in, get text out.

Deliberately built on the standard library only — no Flask, no bundler, no
build step. It binds to localhost by default because it processes local files
and can spend money on API calls; it is a personal tool, not a service.

Conversion runs as a background job rather than inside the HTTP request: a
100-page document can take well over an hour, and holding one connection
open that long is fragile — a phone locking its screen, a laptop sleeping,
or a flaky Wi-Fi hop all kill an in-flight request and lose the whole run.
``POST /convert`` hands back a job id immediately; the caller polls
``GET /jobs/<id>`` for progress and, eventually, the result. The job keeps
running on the server even if nobody is listening.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .config import Settings
from .ingest import SUPPORTED_SUFFIXES

MAX_UPLOAD_BYTES = 200 * 1024 * 1024

#: How long a finished job's result stays available for polling before it is
#: swept away. Generous, since a phone that lost signal mid-job needs to be
#: able to come back later and still find the answer.
JOB_TTL_SECONDS = 6 * 3600

_PAGE_TOTAL_RE = re.compile(r"loaded (\d+) page\(s\)")
_PAGE_DONE_RE = re.compile(r"^page (\d+) done \(")


def parse_multipart(body: bytes, boundary: bytes) -> Tuple[List[Tuple[str, bytes]], Dict[str, str]]:
    """Minimal multipart/form-data parser (files and plain fields).

    Only ever strips the exact CRLF that RFC 2046 puts around a part's body
    (one after the boundary line, one before the next boundary) — never an
    arbitrary run of ``\r``/``\n``. A blanket strip would corrupt any binary
    upload whose last byte happens to be 0x0D or 0x0A, which is not rare
    enough to ignore for photos and PDFs coming from a phone.
    """
    files: List[Tuple[str, bytes]] = []
    fields: Dict[str, str] = {}
    delimiter = b"--" + boundary
    raw_parts = body.split(delimiter)
    # The first split segment is whatever preceded the opening boundary
    # (normally empty) and the last is the closing "--\r\n" tail; only the
    # segments between are real parts.
    for part in raw_parts[1:-1]:
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        header_blob, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
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
        if filename_match and filename_match.group(1):
            files.append((Path(filename_match.group(1)).name, content))
        else:
            fields[name_match.group(1)] = content.decode("utf-8", "replace")
    return files, fields


# -- background jobs --------------------------------------------------------
@dataclass
class Job:
    id: str
    status: str = "queued"  # queued | running | done | error
    log: List[str] = field(default_factory=list)
    pages_total: Optional[int] = None
    pages_done: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "pages_total": self.pages_total,
            "pages_done": self.pages_done,
            "log": list(self.log[-200:]),
            "result": self.result,
            "error": self.error,
        }

    def note(self, message: str) -> None:
        self.log.append(message)
        if self.pages_total is None:
            total_match = _PAGE_TOTAL_RE.search(message)
            if total_match:
                self.pages_total = int(total_match.group(1))
        if _PAGE_DONE_RE.match(message):
            self.pages_done += 1


class JobStore:
    """Every job the server has run recently, keyed by id."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(id=uuid.uuid4().hex)
        with self._lock:
            self._sweep_locked()
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def _sweep_locked(self) -> None:
        cutoff = time.time() - JOB_TTL_SECONDS
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.finished_at is not None and job.finished_at < cutoff
        ]
        for job_id in expired:
            del self._jobs[job_id]


JOBS = JobStore()


def _run_job(job: Job, settings: Settings, paths: List[Path], workdir: Path) -> None:
    job.status = "running"
    try:
        from .pipeline import Pipeline

        pipeline = Pipeline(settings, progress=job.note)
        result = pipeline.run(paths)
        corrections = sum(1 for page in result.pages for c in page.corrections if c.get("applied"))
        job.result = {
            "text": result.text,
            "confidence": round(result.confidence, 4),
            "words": result.stats.get("words", 0),
            "pages": result.stats.get("pages", 0),
            "corrections": corrections,
            "low_confidence_pages": [p.index + 1 for p in result.low_confidence_pages()],
            "log": list(job.log) + result.warnings,
        }
        job.status = "done"
    except Exception as exc:  # noqa: BLE001 — reported to the caller, not raised
        job.error = str(exc)
        job.status = "error"
    finally:
        job.finished_at = time.time()
        shutil.rmtree(workdir, ignore_errors=True)


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
  .progress {{ height: 8px; border-radius: 4px; background: var(--line); overflow: hidden; margin-top: .5rem; }}
  .progress > div {{ height: 100%; background: var(--accent); width: 0%; transition: width .3s; }}
  .progress-label {{ font-size: .85rem; color: var(--muted); margin-top: .35rem; }}
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
      <label class="opt"><input type="checkbox" id="stripheaders"> حذفِ سربرگ/پابرگ/واترمارکِ تکراری</label>
      <label class="opt">پاس‌ها:
        <select id="passes"><option>1</option><option selected>2</option><option>3</option></select>
      </label>
      <button id="run" disabled>تبدیل کن</button>
    </div>
    <div class="progress hidden" id="progressBar"><div id="progressFill"></div></div>
    <div class="progress-label hidden" id="progressLabel"></div>
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
const progressBar = document.getElementById('progressBar');
const progressFill = document.getElementById('progressFill');
const progressLabel = document.getElementById('progressLabel');
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

function sleep(ms) {{ return new Promise(r => setTimeout(r, ms)); }}

async function pollJob(jobId) {{
  while (true) {{
    const response = await fetch('/jobs/' + jobId);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'خطا');

    if (data.pages_total) {{
      const pct = Math.min(100, Math.round(100 * data.pages_done / data.pages_total));
      progressFill.style.width = pct + '%';
      progressLabel.textContent = 'صفحه‌ی ' + data.pages_done + ' از ' + data.pages_total;
    }} else {{
      progressLabel.textContent = (data.log[data.log.length - 1]) || 'در حالِ آماده‌سازی…';
    }}

    if (data.status === 'done') return data.result;
    if (data.status === 'error') throw new Error(data.error || 'خطا');
    await sleep(2000);
  }}
}}

runButton.addEventListener('click', async () => {{
  runButton.disabled = true;
  const original = runButton.textContent;
  runButton.textContent = 'در حالِ ارسال…';
  progressBar.classList.remove('hidden');
  progressLabel.classList.remove('hidden');
  progressFill.style.width = '0%';
  const form = new FormData();
  chosen.forEach(file => form.append('files', file));
  form.append('verify', document.getElementById('verify').checked ? '1' : '0');
  form.append('normalize', document.getElementById('normalize').checked ? '1' : '0');
  form.append('page_numbers', document.getElementById('pagenums').checked ? '1' : '0');
  form.append('strip_headers', document.getElementById('stripheaders').checked ? '1' : '0');
  form.append('passes', document.getElementById('passes').value);
  try {{
    const submit = await fetch('/convert', {{ method: 'POST', body: form }});
    const submitData = await submit.json();
    if (!submit.ok) throw new Error(submitData.error || 'خطا');
    runButton.textContent = 'در حالِ خواندن…';
    const data = await pollJob(submitData.job_id);

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
    progressBar.classList.add('hidden');
    progressLabel.classList.add('hidden');
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

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.format(version=__version__).encode("utf-8"), "text/html; charset=utf-8")
            return
        if self.path.startswith("/jobs/"):
            job_id = self.path[len("/jobs/") :]
            job = JOBS.get(job_id)
            if job is None:
                self._error(404, "no such job (it may have expired)")
                return
            self._send_json(200, job.snapshot())
            return
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
                strip_repeated_boundaries=fields.get("strip_headers", "0") == "1",
                passes=max(1, min(3, int(fields.get("passes", "2") or 2))),
                cache_dir=workdir / "cache",
            )
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(workdir, ignore_errors=True)
            self._error(400, f"bad request: {exc}")
            return

        job = JOBS.create()
        thread = threading.Thread(target=_run_job, args=(job, settings, paths, workdir), daemon=True)
        thread.start()
        self._send_json(202, {"job_id": job.id})

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": html.escape(message)})


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
