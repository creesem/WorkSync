"""Provider seam for the optional local model (Ollama or an OpenAI-compatible endpoint).

The model is suggestion-only: this module turns a prompt into a parsed JSON object or
``None``. It never writes and never raises for an unavailable endpoint, so a caller can
always fall back to a deterministic result. Provider, endpoint, model, and budgets are
read from machine config; no development-machine path is baked in.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_PROVIDER = "ollama"
DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:1.7b"
DEFAULT_TIMEOUT = 30
DEFAULT_NUM_CTX = 4096
DEFAULT_NUM_PREDICT = 512


@dataclass(frozen=True)
class ModelConfig:
    """Resolved local-model settings."""

    provider: str = DEFAULT_PROVIDER
    endpoint: str = DEFAULT_ENDPOINT
    model: str = DEFAULT_MODEL
    timeout: int = DEFAULT_TIMEOUT
    num_ctx: int = DEFAULT_NUM_CTX
    num_predict: int = DEFAULT_NUM_PREDICT

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | None) -> ModelConfig:
        """Build a config from machine-config keys, falling back to safe defaults."""
        data = raw or {}

        def _text(key: str, default: str) -> str:
            value = data.get(key)
            text = str(value).strip() if value is not None else ""
            return text or default

        return cls(
            provider=_text("local_model_provider", DEFAULT_PROVIDER).casefold(),
            endpoint=_text("local_model_endpoint", DEFAULT_ENDPOINT),
            model=_text("local_model", DEFAULT_MODEL),
            timeout=_as_int(data.get("local_model_timeout"), DEFAULT_TIMEOUT),
            num_ctx=_as_int(data.get("local_model_num_ctx"), DEFAULT_NUM_CTX),
            num_predict=_as_int(data.get("local_model_num_predict"), DEFAULT_NUM_PREDICT),
        )

    @classmethod
    def configured(cls, raw: dict[str, Any] | None) -> bool:
        """Return True when the machine config opts into the local model."""
        data = raw or {}
        return any(
            str(data.get(key) or "").strip() for key in ("local_model", "local_model_provider", "local_model_endpoint")
        )


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


class LocalModel:
    """A bounded, suggestion-only client for the configured local model."""

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig()

    def suggest(self, prompt: str, schema: dict) -> dict | None:
        """Return the model's structured suggestion, or ``None`` when unavailable."""
        try:
            text = self._generate(prompt, schema)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return None
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _generate(self, prompt: str, schema: dict) -> str:
        if self.config.provider in {"openai", "openai-compatible", "opencode"}:
            return self._generate_openai(prompt)
        return self._generate_ollama(prompt, schema)

    def _generate_ollama(self, prompt: str, schema: dict) -> str:
        body = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {
                "temperature": 0,
                "num_ctx": self.config.num_ctx,
                "num_predict": self.config.num_predict,
            },
        }
        payload = _post_json(f"{self.config.endpoint.rstrip('/')}/api/generate", body, self.config.timeout)
        if payload.get("error"):
            raise ValueError(f"local model error: {payload['error']}")
        return str(payload.get("response") or "")

    def _generate_openai(self, prompt: str) -> str:
        body = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": self.config.num_predict,
        }
        payload = _post_json(f"{self.config.endpoint.rstrip('/')}/v1/chat/completions", body, self.config.timeout)
        if payload.get("error"):
            error = payload["error"]
            message = error.get("message", error) if isinstance(error, dict) else error
            raise ValueError(f"local model error: {message}")
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return str(message.get("content") or choice.get("text") or "")


def _post_json(url: str, body: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}
