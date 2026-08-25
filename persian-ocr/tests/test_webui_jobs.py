"""End-to-end tests of the async job API a real client (browser or the
Android app) actually talks to: submit, poll, get a result — over real HTTP
against a real running server. The engine is replaced with a scripted one
that always succeeds, so these tests exercise the job plumbing (threading,
polling, progress parsing, error propagation) rather than OCR accuracy.
"""

import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer

import pytest

from persian_ocr.config import Settings
from persian_ocr.engines.base import Block, EngineError, PageReading
from persian_ocr.engines.mock import MockEngine
from persian_ocr.webui import Handler


def _steady_reader(image_bytes, media_type, *, tile_index=0, tile_total=1, pass_index=0):
    return PageReading(blocks=[Block("paragraph", "متنِ آزمایشی")], engine="mock")


def _failing_reader(image_bytes, media_type, *, tile_index=0, tile_total=1, pass_index=0):
    raise EngineError("simulated engine failure")


def _make_server(monkeypatch, reader=_steady_reader):
    monkeypatch.setattr(
        "persian_ocr.pipeline.build_engine",
        lambda settings: MockEngine(settings, reader=reader),
    )
    Handler.settings = Settings(engine="mock", verify=False, quiet=True, use_cache=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{port}"


@pytest.fixture
def running_server(monkeypatch):
    server, url = _make_server(monkeypatch)
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()


def _post_multipart(url: str, fields: dict, files: dict) -> tuple:
    boundary = f"test-{uuid.uuid4().hex}"
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, (filename, data, mime) in files.items():
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'
            ).encode()
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    request = urllib.request.Request(
        f"{url}/convert", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        response = urllib.request.urlopen(request, timeout=10)
        return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _get_json(url: str) -> tuple:
    try:
        response = urllib.request.urlopen(url, timeout=10)
        return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _tiny_png() -> bytes:
    # A real, valid PNG — enough for the ingest layer to accept as an image;
    # the scripted engine never actually reads pixels.
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _poll_until_terminal(url: str, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    payload = None
    while time.time() < deadline:
        status, payload = _get_json(f"{url}/jobs/{job_id}")
        assert status == 200
        if payload["status"] in ("done", "error"):
            return payload
        time.sleep(0.05)
    raise AssertionError(f"job did not finish within {timeout}s: {payload}")


def test_convert_returns_a_job_id_immediately(running_server):
    status, payload = _post_multipart(
        running_server, {"passes": "1"}, {"files": ("page.png", _tiny_png(), "image/png")}
    )
    assert status == 202
    assert "job_id" in payload and payload["job_id"]


def test_polling_reaches_done_and_returns_the_result(running_server):
    _, submitted = _post_multipart(
        running_server, {"passes": "1"}, {"files": ("page.png", _tiny_png(), "image/png")}
    )
    payload = _poll_until_terminal(running_server, submitted["job_id"])

    assert payload["status"] == "done"
    assert "متنِ آزمایشی" in payload["result"]["text"]
    assert payload["result"]["pages"] == 1


def test_a_failing_engine_surfaces_as_a_job_error(monkeypatch):
    server, url = _make_server(monkeypatch, reader=_failing_reader)
    try:
        _, submitted = _post_multipart(
            url, {"passes": "1"}, {"files": ("page.png", _tiny_png(), "image/png")}
        )
        payload = _poll_until_terminal(url, submitted["job_id"])
        assert payload["status"] == "error"
        assert payload["error"]
        assert payload["result"] is None
    finally:
        server.shutdown()
        server.server_close()


def test_an_unknown_job_id_is_a_404(running_server):
    status, payload = _get_json(f"{running_server}/jobs/does-not-exist")
    assert status == 404
    assert "error" in payload


def test_a_request_with_no_files_is_rejected_before_a_job_is_created(running_server):
    status, payload = _post_multipart(running_server, {}, {})
    assert status == 400
    assert "error" in payload


def test_a_real_image_is_accepted_despite_a_nameless_filename(running_server):
    # Some content providers (a phone gallery app, a share-sheet forward) hand
    # a client a display name with no extension at all, even though the bytes
    # are unambiguously a real image. The server should sniff the actual
    # content rather than reject solely because the filename has no suffix.
    status, payload = _post_multipart(
        running_server,
        {"passes": "1"},
        {"files": ("IMG20260825", _tiny_png(), "application/octet-stream")},
    )
    assert status == 202
    assert "job_id" in payload and payload["job_id"]


def test_a_real_image_is_accepted_despite_a_wrong_extension(running_server):
    status, payload = _post_multipart(
        running_server,
        {"passes": "1"},
        {"files": ("page.bin", _tiny_png(), "application/octet-stream")},
    )
    assert status == 202
    assert "job_id" in payload and payload["job_id"]


def test_a_file_that_is_not_actually_a_supported_type_is_still_rejected(running_server):
    status, payload = _post_multipart(
        running_server,
        {},
        {"files": ("notes.txt", b"just some plain text, not an image", "text/plain")},
    )
    assert status == 400
    assert "error" in payload


def test_progress_is_visible_while_a_job_is_running(running_server):
    _, submitted = _post_multipart(
        running_server, {"passes": "1"}, {"files": ("page.png", _tiny_png(), "image/png")}
    )
    job_id = submitted["job_id"]

    seen_pages_total = False
    deadline = time.time() + 15
    while time.time() < deadline:
        status, payload = _get_json(f"{running_server}/jobs/{job_id}")
        assert payload["status"] in ("queued", "running", "done", "error")
        if payload.get("pages_total"):
            seen_pages_total = True
        if payload["status"] in ("done", "error"):
            break
        time.sleep(0.05)

    assert seen_pages_total


def test_strip_headers_option_reaches_the_pipeline(monkeypatch):
    seen_settings = {}

    import persian_ocr.webui as webui_module

    original_run_job = webui_module._run_job

    def spying_run_job(job, settings, paths, workdir):
        seen_settings["strip"] = settings.strip_repeated_boundaries
        return original_run_job(job, settings, paths, workdir)

    monkeypatch.setattr(webui_module, "_run_job", spying_run_job)
    server, url = _make_server(monkeypatch)
    try:
        _, submitted = _post_multipart(
            url,
            {"passes": "1", "strip_headers": "1"},
            {"files": ("page.png", _tiny_png(), "image/png")},
        )
        _poll_until_terminal(url, submitted["job_id"])
        assert seen_settings["strip"] is True
    finally:
        server.shutdown()
        server.server_close()
