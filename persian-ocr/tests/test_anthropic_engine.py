"""Request-shape tests for the vision engine.

No network: a stub stands in for the SDK client, so the assembled request —
model, image block, schema, effort, beta flags — is checked exactly as it would
be sent.
"""

import base64
import json

import pytest

from persian_ocr.config import Settings, supports_effort, supports_server_fallback
from persian_ocr.engines.anthropic_vision import AnthropicVisionEngine
from persian_ocr.engines.base import Block, EngineError

READING = {
    "page_number": "۵",
    "blocks": [{"type": "paragraph", "text": "متنِ آزمایشی"}],
    "ignored_overlays": ["Edit PDF"],
    "uncertain_spans": [],
    "legibility": "high",
}


class StubBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class StubUsage:
    input_tokens = 1200
    output_tokens = 340


class StubResponse:
    stop_reason = "end_turn"
    stop_details = None

    def __init__(self, payload):
        self.content = [StubBlock(json.dumps(payload, ensure_ascii=False))]
        self.usage = StubUsage()


class StubMessages:
    def __init__(self, payload, recorder):
        self._payload = payload
        self._recorder = recorder

    def create(self, **kwargs):
        self._recorder.append(kwargs)
        return StubResponse(self._payload)


class StubClient:
    def __init__(self, payload, recorder, beta_recorder=None):
        self.messages = StubMessages(payload, recorder)

        class Beta:
            pass

        self.beta = Beta()
        self.beta.messages = StubMessages(payload, beta_recorder if beta_recorder is not None else recorder)


def engine_with(payload, settings=None, recorder=None, beta_recorder=None):
    settings = settings or Settings(api_key="test-key")
    engine = AnthropicVisionEngine(settings)
    engine._client = StubClient(payload, recorder if recorder is not None else [], beta_recorder)
    return engine


def test_a_reading_is_parsed_into_blocks():
    engine = engine_with(READING)
    reading = engine.read(b"PNGDATA", "image/png")
    assert reading.blocks[0].text == "متنِ آزمایشی"
    assert reading.page_number == "۵"
    assert reading.ignored_overlays == ["Edit PDF"]
    assert reading.usage["input_tokens"] == 1200
    assert reading.engine.startswith("anthropic:")


def test_the_request_carries_the_image_and_the_schema():
    sent = []
    engine = engine_with(READING, Settings(api_key="k", server_fallbacks=False), recorder=sent)
    engine.read(b"PNGDATA", "image/png", tile_index=1, tile_total=3, pass_index=0)

    request = sent[0]
    assert request["model"] == "claude-opus-5"
    content = request["messages"][0]["content"]
    image = content[0]
    assert image["type"] == "image"
    assert image["source"]["media_type"] == "image/png"
    assert base64.standard_b64decode(image["source"]["data"]) == b"PNGDATA"
    assert "slice 2 of 3" in content[1]["text"].lower()
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "transcriber" in request["system"].lower()


def test_effort_and_thinking_only_go_to_models_that_take_them():
    sent = []
    engine_with(READING, Settings(api_key="k", server_fallbacks=False), recorder=sent).read(b"x", "image/png")
    assert sent[0]["output_config"]["effort"] == "medium"
    assert sent[0]["thinking"] == {"type": "adaptive"}

    sent = []
    old_model = Settings(api_key="k", model="claude-haiku-4-5", server_fallbacks=False)
    engine_with(READING, old_model, recorder=sent).read(b"x", "image/png")
    assert "effort" not in sent[0]["output_config"]
    assert "thinking" not in sent[0]


def test_refusal_fallbacks_are_requested_on_a_model_that_supports_them():
    beta_sent = []
    engine_with(READING, Settings(api_key="k"), recorder=[], beta_recorder=beta_sent).read(b"x", "image/png")
    assert beta_sent[0]["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in beta_sent[0]["betas"]


def test_each_pass_gets_a_different_framing():
    sent = []
    engine = engine_with(READING, Settings(api_key="k", server_fallbacks=False), recorder=sent)
    engine.read(b"x", "image/png", pass_index=0)
    engine.read(b"x", "image/png", pass_index=1)
    assert sent[0]["messages"][0]["content"][1]["text"] != sent[1]["messages"][0]["content"][1]["text"]


def test_verification_sends_every_slice_and_the_numbered_blocks():
    sent = []
    engine = engine_with(
        {"verdict": "clean", "corrections": [], "missing_text": [], "notes": ""},
        Settings(api_key="k", server_fallbacks=False),
        recorder=sent,
    )
    payload = engine.verify(
        [(b"one", "image/png"), (b"two", "image/png")],
        [Block("paragraph", "بندِ نخست"), Block("paragraph", "بندِ دوم")],
        ["a suspicious word"],
    )
    assert payload["verdict"] == "clean"

    content = sent[0]["messages"][0]["content"]
    assert sum(1 for part in content if part["type"] == "image") == 2
    prompt = content[-1]["text"]
    assert "[0] بندِ نخست" in prompt and "[1] بندِ دوم" in prompt
    assert "a suspicious word" in prompt
    assert "proof-reader" in sent[0]["system"]


def test_a_refusal_is_reported_clearly():
    class Refusing(StubMessages):
        def create(self, **kwargs):
            response = StubResponse(READING)
            response.stop_reason = "refusal"
            return response

    engine = engine_with(READING, Settings(api_key="k", server_fallbacks=False))
    engine._client.messages = Refusing(READING, [])
    with pytest.raises(EngineError, match="declined"):
        engine.read(b"x", "image/png")


def test_hitting_the_token_ceiling_suggests_a_fix():
    class Truncating(StubMessages):
        def create(self, **kwargs):
            response = StubResponse(READING)
            response.stop_reason = "max_tokens"
            return response

    engine = engine_with(READING, Settings(api_key="k", server_fallbacks=False))
    engine._client.messages = Truncating(READING, [])
    with pytest.raises(EngineError, match="token ceiling"):
        engine.read(b"x", "image/png")


def test_a_non_json_reply_is_reported():
    class Chatty(StubMessages):
        def create(self, **kwargs):
            response = StubResponse(READING)
            response.content = [StubBlock("not json at all")]
            return response

    engine = engine_with(READING, Settings(api_key="k", server_fallbacks=False))
    engine._client.messages = Chatty(READING, [])
    with pytest.raises(EngineError, match="JSON"):
        engine.read(b"x", "image/png")


@pytest.mark.parametrize(
    "model,effort,fallback",
    [
        ("claude-opus-5", True, True),
        ("claude-sonnet-5", True, False),
        ("claude-haiku-4-5", False, False),
    ],
)
def test_model_capability_table(model, effort, fallback):
    assert supports_effort(model) is effort
    assert supports_server_fallback(model) is fallback
