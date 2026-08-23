"""Engine that drives the Claude Code CLI instead of the HTTP API.

The point of this engine is that it needs **no API key**. If `claude` is
installed and signed in — the ordinary Claude Code setup — this engine borrows
that session, so the same vision model reads the pages and the work counts
against the existing subscription rather than a separate API bill.

Mechanically it runs `claude --print` with a replacement system prompt, hands
the model the page image as a file to Read, and parses the JSON it returns.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import Settings
from ..prompts import (
    OCR_SCHEMA,
    OCR_SYSTEM,
    VERIFY_FLAGS_TEMPLATE,
    VERIFY_SCHEMA,
    VERIFY_SYSTEM,
    VERIFY_USER_TEMPLATE,
    ocr_user_prompt,
)
from .base import Block, EngineError, PageReading

JSON_INSTRUCTION = (
    "\n\nReturn ONLY a JSON object matching this schema. No prose, no "
    "explanation, no markdown fence:\n{schema}\n"
)

#: `claude --model` takes an alias or a full name; map the API ids we use.
MODEL_ALIASES = {
    "claude-opus-5": "opus",
    "claude-sonnet-5": "sonnet",
    "claude-haiku-4-5": "haiku",
    "claude-fable-5": "fable",
}

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)

#: Turn budgets. Reading is one look and one answer; proof-reading legitimately
#: revisits the image several times, zooming into the spans it was asked about.
READ_TURNS = 6
VERIFY_TURNS = 12


def _parse_envelope(stdout: str) -> Optional[Dict[str, Any]]:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return envelope if isinstance(envelope, dict) else None


def _out_of_turns(envelope: Optional[Dict[str, Any]]) -> bool:
    """True when the CLI stopped mid-task rather than because it was done."""
    if not envelope or not envelope.get("is_error"):
        return False
    return envelope.get("stop_reason") in {"tool_use", "max_turns"} or "max turns" in str(
        envelope.get("result", "")
    ).lower()


def extract_json(text: str) -> Dict[str, Any]:
    """Pull a JSON object out of a CLI reply that may be fenced or chatty."""
    cleaned = _FENCE_RE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise EngineError(f"the CLI did not return JSON: {text[:200]!r}")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise EngineError(f"could not parse the CLI's JSON reply: {exc}") from exc


class ClaudeCliEngine:
    name = "claude-cli"

    def __init__(self, settings: Settings, executable: Optional[str] = None):
        self.settings = settings
        self.executable = executable or os.environ.get("PERSIAN_OCR_CLAUDE_BIN") or shutil.which("claude")
        if not self.executable:
            raise EngineError(
                "the `claude` CLI was not found. Install Claude Code "
                "(https://claude.com/claude-code) and sign in, or use "
                "--engine anthropic with an API key."
            )
        self.total_cost_usd = 0.0

    @property
    def supports_verification(self) -> bool:
        return True

    # -- plumbing ----------------------------------------------------------
    def _model_argument(self, model: str) -> str:
        return MODEL_ALIASES.get(model, model)

    def _invoke(self, prompt: str, system: str, image_paths: Sequence[Path],
                model: str, max_turns: int) -> Tuple[int, str, str]:
        directories = {str(path.parent) for path in image_paths}
        command = [
            self.executable,
            "--print",
            prompt,
            "--system-prompt",
            system,
            "--allowedTools",
            "Read",
            "--max-turns",
            str(max_turns),
            "--model",
            self._model_argument(model),
            "--output-format",
            "json",
        ]
        for directory in sorted(directories):
            command += ["--add-dir", directory]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=self.settings.request_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise EngineError(
                f"the claude CLI timed out after {self.settings.request_timeout:.0f}s"
            ) from exc
        return (
            completed.returncode,
            completed.stdout.decode("utf-8", "replace"),
            completed.stderr.decode("utf-8", "replace"),
        )

    def _run(self, prompt: str, system: str, image_paths: Sequence[Path], model: str,
             max_turns: int) -> Dict[str, Any]:
        returncode, stdout, stderr = self._invoke(prompt, system, image_paths, model, max_turns)
        envelope = _parse_envelope(stdout)

        # Proof-reading a page legitimately takes several looks at the image.
        # When the CLI stops because it ran out of turns rather than because it
        # was finished, give it a bigger budget once before giving up — and say
        # so plainly if it still fails, instead of reporting an empty stderr.
        if _out_of_turns(envelope):
            returncode, stdout, stderr = self._invoke(
                prompt, system, image_paths, model, max_turns * 2
            )
            envelope = _parse_envelope(stdout)

        if envelope is None:
            raise EngineError(
                f"the claude CLI exited {returncode} without a JSON reply: "
                f"{(stderr.strip() or stdout.strip())[:300] or 'no output'}"
            )
        if envelope.get("is_error") or returncode != 0:
            detail = str(envelope.get("result") or stderr.strip() or "")[:300]
            if _out_of_turns(envelope):
                detail = (
                    f"it ran out of turns (stop_reason={envelope.get('stop_reason')}) even with "
                    f"{max_turns * 2}; rerun with a smaller page (--tile-aspect 0.6)"
                )
            raise EngineError(f"the claude CLI reported an error: {detail or 'no detail given'}")

        self.total_cost_usd += float(envelope.get("total_cost_usd") or 0.0)
        usage = envelope.get("usage") or {}
        data = extract_json(envelope.get("result") or "")
        data["_usage"] = {
            "input_tokens": int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_creation_input_tokens") or 0)
            + int(usage.get("cache_read_input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
        }
        return data

    # -- public API --------------------------------------------------------
    def read(
        self,
        image_bytes: bytes,
        media_type: str,
        *,
        tile_index: int = 0,
        tile_total: int = 1,
        pass_index: int = 0,
    ) -> PageReading:
        suffix = ".png" if media_type.endswith("png") else ".jpg"
        with tempfile.TemporaryDirectory(prefix="persian-ocr-") as tmp:
            path = Path(tmp) / f"page{suffix}"
            path.write_bytes(image_bytes)
            prompt = (
                f"Read the image file {path} with the Read tool, then "
                + ocr_user_prompt(tile_index, tile_total, pass_index)
            )
            data = self._run(
                prompt,
                OCR_SYSTEM + JSON_INSTRUCTION.format(schema=json.dumps(OCR_SCHEMA, ensure_ascii=False)),
                [path],
                self.settings.model,
                max_turns=READ_TURNS,
            )

        usage = data.pop("_usage", {})
        reading = PageReading.from_dict(_coerce_reading(data))
        reading.usage = usage
        reading.engine = f"{self.name}:{self._model_argument(self.settings.model)}"
        return reading

    def verify(
        self,
        images: List[Tuple[bytes, str]],
        blocks: List[Block],
        flags: List[str],
    ) -> Dict[str, Any]:
        rendered = "\n".join(f"[{i}] {block.text}" for i, block in enumerate(blocks))
        flag_section = ""
        if flags:
            flag_section = VERIFY_FLAGS_TEMPLATE.format(
                items="\n".join(f"- {flag}" for flag in flags[:60])
            )
        with tempfile.TemporaryDirectory(prefix="persian-ocr-") as tmp:
            paths = []
            for index, (data, media_type) in enumerate(images):
                suffix = ".png" if media_type.endswith("png") else ".jpg"
                path = Path(tmp) / f"slice-{index + 1}{suffix}"
                path.write_bytes(data)
                paths.append(path)

            listing = ", ".join(str(path) for path in paths)
            prompt = (
                f"Read the image file(s) {listing} with the Read tool "
                f"({'they are consecutive slices of one page' if len(paths) > 1 else 'it is one page'}), "
                "then " + VERIFY_USER_TEMPLATE.format(blocks=rendered, flags=flag_section)
            )
            payload = self._run(
                prompt,
                VERIFY_SYSTEM
                + JSON_INSTRUCTION.format(schema=json.dumps(VERIFY_SCHEMA, ensure_ascii=False)),
                paths,
                self.settings.verify_model,
                max_turns=VERIFY_TURNS + 2 * len(paths),
            )
        return _coerce_verification(payload)


def _coerce_reading(data: Dict[str, Any]) -> Dict[str, Any]:
    """Accept near-miss shapes from a CLI reply and fill in what is missing.

    The HTTP engine gets a schema-constrained response; the CLI does not, so a
    reply is occasionally shaped like `{"text": "..."}` instead of the block
    list. Rescuing those is much better than throwing the page away.
    """
    if not isinstance(data, dict):
        raise EngineError("the CLI returned something that is not a JSON object")

    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        text = data.get("text") or data.get("content") or ""
        if not isinstance(text, str) or not text.strip():
            raise EngineError("the CLI returned no text for this page")
        blocks = [
            {"type": "paragraph", "text": chunk.strip()}
            for chunk in text.split("\n\n")
            if chunk.strip()
        ]

    normalised = []
    for block in blocks:
        if isinstance(block, str):
            normalised.append({"type": "paragraph", "text": block})
        elif isinstance(block, dict) and str(block.get("text", "")).strip():
            normalised.append(
                {"type": str(block.get("type") or "paragraph"), "text": str(block["text"])}
            )

    page_number = data.get("page_number")
    return {
        "blocks": normalised,
        "page_number": page_number if isinstance(page_number, str) else None,
        "ignored_overlays": [str(x) for x in data.get("ignored_overlays") or []],
        "uncertain_spans": [x for x in data.get("uncertain_spans") or [] if isinstance(x, dict)],
        "legibility": data.get("legibility") if data.get("legibility") in {"high", "medium", "low"} else "high",
    }


def _coerce_verification(payload: Dict[str, Any]) -> Dict[str, Any]:
    usage = payload.get("_usage", {})
    return {
        "verdict": payload.get("verdict") if payload.get("verdict") in
        {"clean", "corrected", "unreadable"} else "corrected",
        "corrections": [c for c in payload.get("corrections") or [] if isinstance(c, dict)],
        "missing_text": [m for m in payload.get("missing_text") or [] if isinstance(m, dict)],
        "notes": str(payload.get("notes") or ""),
        "_usage": usage,
    }
