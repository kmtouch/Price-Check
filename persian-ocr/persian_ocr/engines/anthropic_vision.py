"""Claude vision OCR — the primary, high-accuracy engine.

Why a vision model rather than a classical OCR engine: Persian book typography
is cursive, context-shaped and dot-dense, and the meaning-carrying details
(half-spaces, ezafe kasras, « » quotation, footnote markers) are exactly what
glyph-classifier OCR loses. A vision model reads the page the way a person
does, and — just as importantly — can be told to *report* what it could not
read instead of inventing it.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from ..config import Settings, supports_effort, supports_server_fallback
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

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicVisionEngine:
    name = "anthropic"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None
        self._fallbacks_enabled = settings.server_fallbacks and supports_server_fallback(settings.model)

    # -- client ------------------------------------------------------------
    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise EngineError(
                    "the Anthropic SDK is missing — install it with `pip install anthropic`"
                ) from exc

            kwargs: Dict[str, Any] = {
                "timeout": self.settings.request_timeout,
                "max_retries": self.settings.max_retries,
            }
            if self.settings.resolved_api_key():
                kwargs["api_key"] = self.settings.resolved_api_key()
            if self.settings.base_url:
                kwargs["base_url"] = self.settings.base_url
            try:
                self._client = anthropic.Anthropic(**kwargs)
            except TypeError as exc:
                raise EngineError(
                    "no Anthropic credentials found. Set ANTHROPIC_API_KEY, pass --api-key, "
                    "or run `ant auth login`."
                ) from exc
        return self._client

    @property
    def supports_verification(self) -> bool:
        return True

    # -- low-level request -------------------------------------------------
    def _request(
        self,
        *,
        model: str,
        system: str,
        content: List[Dict[str, Any]],
        schema: Dict[str, Any],
        effort: str,
    ) -> Dict[str, Any]:
        import anthropic

        params: Dict[str, Any] = {
            "model": model,
            "max_tokens": self.settings.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        if supports_effort(model):
            params["output_config"]["effort"] = effort
            params["thinking"] = {"type": "adaptive"}

        use_fallbacks = self._fallbacks_enabled and model == self.settings.model

        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                if use_fallbacks:
                    response = self.client.beta.messages.create(
                        betas=[FALLBACK_BETA], fallbacks="default", **params
                    )
                else:
                    response = self.client.messages.create(**params)
                break
            except anthropic.BadRequestError as exc:
                message = str(exc)
                # Gracefully shed optional features the endpoint rejects rather
                # than failing a whole run over a beta flag.
                if use_fallbacks:
                    use_fallbacks = False
                    self._fallbacks_enabled = False
                    last_error = exc
                    continue
                if "thinking" in message and "thinking" in params:
                    params.pop("thinking", None)
                    last_error = exc
                    continue
                if "effort" in message and "effort" in params["output_config"]:
                    params["output_config"].pop("effort", None)
                    last_error = exc
                    continue
                raise EngineError(f"request rejected by the API: {exc}") from exc
            except anthropic.RateLimitError as exc:  # pragma: no cover - live only
                last_error = exc
                time.sleep(2 ** attempt * 5)
            except anthropic.APIConnectionError as exc:  # pragma: no cover - live only
                last_error = exc
                time.sleep(2 ** attempt * 2)
            except anthropic.APIStatusError as exc:  # pragma: no cover - live only
                raise EngineError(f"API error {exc.status_code}: {exc}") from exc
        else:
            raise EngineError(f"the request kept failing: {last_error}")

        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            raise EngineError(
                "the model declined this image"
                + (f" ({getattr(details, 'category', None)})" if details else "")
            )
        if getattr(response, "stop_reason", None) == "max_tokens":
            raise EngineError(
                "the reply hit the token ceiling — rerun with a larger --max-tokens "
                "or smaller tiles (--tile-aspect 0.6)"
            )

        text = next((block.text for block in response.content if block.type == "text"), "")
        if not text.strip():
            raise EngineError("the model returned an empty response")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise EngineError(f"could not parse the model's JSON reply: {exc}") from exc

        usage = getattr(response, "usage", None)
        data["_usage"] = {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        }
        return data

    @staticmethod
    def _image_block(image_bytes: bytes, media_type: str) -> Dict[str, Any]:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(image_bytes).decode("ascii"),
            },
        }

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
        data = self._request(
            model=self.settings.model,
            system=OCR_SYSTEM,
            content=[
                self._image_block(image_bytes, media_type),
                {"type": "text", "text": ocr_user_prompt(tile_index, tile_total, pass_index)},
            ],
            schema=OCR_SCHEMA,
            effort=self.settings.ocr_effort,
        )
        usage = data.pop("_usage", {})
        reading = PageReading.from_dict(data)
        reading.usage = usage
        reading.engine = f"{self.name}:{self.settings.model}"
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
        content: List[Dict[str, Any]] = []
        for position, (image_bytes, media_type) in enumerate(images):
            if len(images) > 1:
                content.append(
                    {"type": "text", "text": f"Slice {position + 1} of {len(images)} of the same page:"}
                )
            content.append(self._image_block(image_bytes, media_type))
        content.append(
            {
                "type": "text",
                "text": VERIFY_USER_TEMPLATE.format(blocks=rendered, flags=flag_section),
            }
        )
        return self._request(
            model=self.settings.verify_model,
            system=VERIFY_SYSTEM,
            content=content,
            schema=VERIFY_SCHEMA,
            effort=self.settings.verify_effort,
        )
