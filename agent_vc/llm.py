"""OpenAI-compatible LLM client with JSON retries."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any


class LLMError(RuntimeError):
    """Raised when the LLM call fails or returns unusable JSON."""


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM JSON root must be an object")
    return value


def call_json(system_prompt: str, user_payload: dict[str, Any], *, max_retries: int | None = None) -> dict[str, Any]:
    """Call an OpenAI-compatible chat completions endpoint and return JSON."""

    api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMError("LLM_API_KEY is not set")

    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/chat/completions")
    model = os.getenv("LLM_MODEL", "deepseek-chat")
    timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "12"))
    if max_retries is None:
        max_retries = int(os.getenv("LLM_MAX_RETRIES", "0"))

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ],
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.2")),
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    context = _ssl_context()

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            base_url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
                raw = response.read().decode("utf-8")
            payload = json.loads(raw)
            content = payload["choices"][0]["message"]["content"]
            return _extract_json(content)
        except (KeyError, ValueError, json.JSONDecodeError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(0.75 * (attempt + 1))

    raise LLMError(f"LLM call failed: {last_error}")


def _ssl_context() -> ssl.SSLContext | None:
    """Return an SSL context for the LLM request.

    Some local macOS Python installs have an empty OpenSSL cert store. Keep
    verification on by default, but allow an explicit local-dev override.
    """

    if os.getenv("LLM_SSL_VERIFY", "1") == "0":
        return ssl._create_unverified_context()
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except ModuleNotFoundError:
        return None
