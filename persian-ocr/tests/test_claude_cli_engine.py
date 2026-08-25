"""Tests for the key-free engine that drives the Claude Code CLI.

The subprocess is stubbed, so the command line, the prompts and the reply
handling are all checked without spending a request.
"""

import json
import subprocess

import pytest

from persian_ocr.config import Settings
from persian_ocr.engines import resolve_engine
from persian_ocr.engines.base import Block, EngineError
from persian_ocr.engines.claude_cli import ClaudeCliEngine, extract_json

READING = {
    "page_number": "۵",
    "blocks": [{"type": "paragraph", "text": "متنِ آزمایشی"}],
    "ignored_overlays": ["Adobe toolbar"],
    "uncertain_spans": [],
    "legibility": "high",
}


class Completed:
    def __init__(self, payload, returncode=0, stderr=b""):
        envelope = {
            "is_error": False,
            "result": payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
            "total_cost_usd": 0.21,
            "usage": {"input_tokens": 10, "cache_creation_input_tokens": 40000,
                      "cache_read_input_tokens": 5, "output_tokens": 900},
        }
        self.stdout = json.dumps(envelope).encode()
        self.stderr = stderr
        self.returncode = returncode


def engine_with(monkeypatch, payload, recorder=None, settings=None):
    settings = settings or Settings(engine="claude-cli")
    engine = ClaudeCliEngine(settings, executable="/usr/bin/claude")

    def fake_run(command, **kwargs):
        if recorder is not None:
            recorder.append(command)
        return Completed(payload)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return engine


def test_json_is_extracted_from_a_fenced_reply():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go:\n{"a": 2}\nhope that helps') == {"a": 2}


def test_a_reply_with_no_json_is_an_error():
    with pytest.raises(EngineError, match="did not return JSON"):
        extract_json("sorry, I could not read that")


def test_a_reading_comes_back_as_blocks(monkeypatch):
    engine = engine_with(monkeypatch, READING)
    reading = engine.read(b"PNGDATA", "image/png")
    assert reading.blocks[0].text == "متنِ آزمایشی"
    assert reading.page_number == "۵"
    assert reading.usage["output_tokens"] == 900
    assert engine.total_cost_usd == pytest.approx(0.21)


def test_a_plain_text_reply_is_rescued_into_blocks(monkeypatch):
    # The CLI is not schema-constrained, so a near-miss shape must not lose the
    # page.
    engine = engine_with(monkeypatch, {"text": "بندِ نخست\n\nبندِ دوم"})
    reading = engine.read(b"x", "image/png")
    assert [block.text for block in reading.blocks] == ["بندِ نخست", "بندِ دوم"]


def test_an_empty_reply_is_an_error(monkeypatch):
    engine = engine_with(monkeypatch, {"blocks": [], "text": ""})
    with pytest.raises(EngineError, match="no text"):
        engine.read(b"x", "image/png")


def test_the_command_line_is_locked_down(monkeypatch):
    sent = []
    engine = engine_with(monkeypatch, READING, recorder=sent)
    engine.read(b"x", "image/png", tile_index=1, tile_total=3)

    command = sent[0]
    assert command[0] == "/usr/bin/claude"
    assert "--print" in command
    # Only Read is granted: the engine must never be able to edit or run things.
    assert command[command.index("--allowedTools") + 1] == "Read"
    assert command[command.index("--output-format") + 1] == "json"
    assert command[command.index("--model") + 1] == "opus"
    system = command[command.index("--system-prompt") + 1]
    assert "transcriber" in system.lower()
    assert "slice 2 of 3" in command[2].lower()


def test_the_verifier_lists_every_slice(monkeypatch):
    sent = []
    engine = engine_with(
        monkeypatch,
        {"verdict": "clean", "corrections": [], "missing_text": [], "notes": ""},
        recorder=sent,
    )
    payload = engine.verify(
        [(b"one", "image/png"), (b"two", "image/png")],
        [Block("paragraph", "بندِ نخست")],
        ["a flag"],
    )
    assert payload["verdict"] == "clean"
    prompt = sent[0][2]
    assert "slice-1.png" in prompt and "slice-2.png" in prompt
    assert "[0] بندِ نخست" in prompt and "a flag" in prompt


class Raw:
    """A CLI run that produced no JSON envelope at all."""

    def __init__(self, returncode, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_a_failing_cli_surfaces_its_stderr(monkeypatch):
    engine = ClaudeCliEngine(Settings(engine="claude-cli"), executable="/usr/bin/claude")
    monkeypatch.setattr(
        subprocess, "run", lambda command, **kwargs: Raw(1, stderr=b"not logged in")
    )
    with pytest.raises(EngineError, match="not logged in"):
        engine.read(b"x", "image/png")


class OutOfTurns:
    """The CLI stopping because it ran out of turns, not because it finished."""

    def __init__(self, payload=None):
        envelope = {
            "is_error": True,
            "stop_reason": "tool_use",
            "result": "",
            "num_turns": 4,
            "usage": {},
        }
        if payload is not None:
            envelope = {"is_error": False, "stop_reason": "end_turn",
                        "result": json.dumps(payload, ensure_ascii=False), "usage": {}}
        self.stdout = json.dumps(envelope).encode()
        self.stderr = b""
        self.returncode = 0 if payload is not None else 1


def test_running_out_of_turns_retries_once_with_a_bigger_budget(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(int(command[command.index("--max-turns") + 1]))
        return OutOfTurns() if len(calls) == 1 else OutOfTurns(READING)

    engine = ClaudeCliEngine(Settings(engine="claude-cli"), executable="/usr/bin/claude")
    monkeypatch.setattr(subprocess, "run", fake_run)

    reading = engine.read(b"x", "image/png")
    assert reading.blocks[0].text == "متنِ آزمایشی"
    assert len(calls) == 2 and calls[1] == calls[0] * 2


def test_running_out_of_turns_twice_says_so(monkeypatch):
    engine = ClaudeCliEngine(Settings(engine="claude-cli"), executable="/usr/bin/claude")
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: OutOfTurns())
    with pytest.raises(EngineError, match="ran out of turns"):
        engine.read(b"x", "image/png")


def test_verification_gets_a_larger_turn_budget_than_reading(monkeypatch):
    sent = []
    engine = engine_with(
        monkeypatch,
        {"verdict": "clean", "corrections": [], "missing_text": [], "notes": ""},
        recorder=sent,
    )
    engine.verify([(b"one", "image/png")], [Block("paragraph", "متن")], [])
    verify_turns = int(sent[0][sent[0].index("--max-turns") + 1])

    sent.clear()
    engine_with(monkeypatch, READING, recorder=sent).read(b"x", "image/png")
    read_turns = int(sent[0][sent[0].index("--max-turns") + 1])

    assert verify_turns > read_turns


def test_a_timeout_is_reported(monkeypatch):
    engine = ClaudeCliEngine(Settings(engine="claude-cli"), executable="/usr/bin/claude")

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(EngineError, match="timed out"):
        engine.read(b"x", "image/png")


def test_a_missing_cli_is_reported_with_a_way_out(monkeypatch):
    monkeypatch.delenv("PERSIAN_OCR_CLAUDE_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(EngineError, match="claude"):
        ClaudeCliEngine(Settings(engine="claude-cli"))


def test_auto_prefers_an_api_key_then_the_cli_then_tesseract(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert resolve_engine("auto") == "anthropic"

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    assert resolve_engine("auto") == "claude-cli"

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/tesseract" if name == "tesseract" else None)
    assert resolve_engine("auto") == "tesseract"

    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(EngineError):
        resolve_engine("auto")


def test_auto_leaves_an_explicit_engine_alone():
    assert resolve_engine("mock") == "mock"
