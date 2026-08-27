from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"


class ProviderError(Exception):
    pass


def _read_json_response(resp: Any) -> dict[str, Any]:
    raw = resp.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Invalid JSON from API: {raw[:500]}") from exc


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any], *, timeout: int = 300) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _read_json_response(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ProviderError(f"HTTP {exc.code}: {body[:800]}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(str(exc)) from exc


def deepseek_api_key() -> str:
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise ProviderError("DEEPSEEK_API_KEY is not set")
    return key


def gemini_api_key() -> str:
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        raise ProviderError("GEMINI_API_KEY or GOOGLE_API_KEY is not set")
    return key


def deepseek_chat(
    messages: list[dict[str, str]],
    *,
    model: str = "deepseek-chat",
    temperature: float = 0.3,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    result = _post_json(
        DEEPSEEK_URL,
        {
            "Authorization": f"Bearer {deepseek_api_key()}",
            "Content-Type": "application/json",
        },
        payload,
    )
    try:
        return str(result["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"Unexpected DeepSeek response: {result!r}") from exc


def gemini_generate(
    prompt: str,
    *,
    system: str | None = None,
    model: str = DEFAULT_GEMINI_MODEL,
    temperature: float = 0.4,
) -> str:
    key = gemini_api_key()
    url = f"{GEMINI_BASE}/{model}:generateContent?key={key}"
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    result = _post_json(url, {"Content-Type": "application/json"}, body)
    try:
        parts = result["candidates"][0]["content"]["parts"]
        texts = [p["text"] for p in parts if "text" in p]
        if not texts:
            raise KeyError("no text parts")
        return "\n".join(texts).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"Unexpected Gemini response: {result!r}") from exc
