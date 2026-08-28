from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODELS_URL = "https://api.deepseek.com/models"
GEMINI_HOST = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_BASE = f"{GEMINI_HOST}/models"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
_MODEL_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_SKIP_GEMINI = re.compile(r"(embedding|imagen|image|veo|tts|audio|robotics|computer-use|lyria|transcribe)", re.I)
_CATALOG_TTL_SEC = 300.0
_catalog_lock = threading.Lock()
_catalog_cache: tuple[float, dict[str, Any]] | None = None


def provider_for_model(model: str) -> str:
    name = (model or "").strip()
    if not _MODEL_NAME.fullmatch(name):
        raise ProviderError(f"Invalid model: {model!r}")
    lower = name.lower()
    if lower.startswith("gemini") or lower.startswith("models-gemini"):
        return "gemini"
    if lower.startswith("deepseek"):
        return "deepseek"
    raise ProviderError(f"Unknown model provider for {model!r}")


def is_gemini_model(model: str) -> bool:
    return provider_for_model(model) == "gemini"


def complete_chat(
    messages: list[dict[str, str]],
    *,
    model: str,
    temperature: float = 0.3,
) -> str:
    if is_gemini_model(model):
        system_parts = [m.get("content") or "" for m in messages if m.get("role") == "system"]
        user_parts = [m.get("content") or "" for m in messages if m.get("role") != "system"]
        return gemini_generate(
            "\n\n".join(part for part in user_parts if part),
            system="\n\n".join(part for part in system_parts if part) or None,
            model=model,
            temperature=temperature,
        )
    return deepseek_chat(messages, model=model, temperature=temperature)


def complete_prompt(
    prompt: str,
    *,
    model: str,
    system: str | None = None,
    temperature: float = 0.4,
) -> str:
    if is_gemini_model(model):
        return gemini_generate(prompt, system=system, model=model, temperature=temperature)
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return deepseek_chat(messages, model=model, temperature=temperature)


class ProviderError(Exception):
    pass


def _read_json_response(resp: Any) -> dict[str, Any]:
    raw = resp.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Invalid JSON from API: {raw[:500]}") from exc


def _request_json(url: str, headers: dict[str, str], *, data: bytes | None = None, timeout: int = 300) -> dict[str, Any]:
    method = "POST" if data is not None else "GET"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _read_json_response(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ProviderError(f"HTTP {exc.code}: {body[:800]}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(str(exc)) from exc


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any], *, timeout: int = 300) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    return _request_json(url, headers, data=data, timeout=timeout)


def _get_json(url: str, headers: dict[str, str], *, timeout: int = 20) -> dict[str, Any]:
    return _request_json(url, headers, timeout=timeout)


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
    model: str = "deepseek-v4-flash",
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
    if not _MODEL_NAME.fullmatch(model):
        raise ProviderError(f"Invalid Gemini model: {model!r}")
    key = gemini_api_key()
    url = f"{GEMINI_BASE}/{model}:generateContent"
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    result = _post_json(
        url,
        {"Content-Type": "application/json", "x-goog-api-key": key},
        body,
    )
    try:
        parts = result["candidates"][0]["content"]["parts"]
        texts = [p["text"] for p in parts if "text" in p]
        if not texts:
            raise KeyError("no text parts")
        return "\n".join(texts).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"Unexpected Gemini response: {result!r}") from exc


def _pretty_deepseek_label(model_id: str) -> str:
    rest = re.sub(r"^deepseek-?", "", model_id, flags=re.I).strip("-_ ")
    if not rest:
        return "DeepSeek"
    parts = [p for p in re.split(r"[-_]+", rest) if p]
    pretty = " ".join(p.upper() if re.fullmatch(r"v\d+", p, re.I) else p.capitalize() for p in parts)
    return f"DeepSeek {pretty}".strip()


def list_deepseek_models() -> list[dict[str, Any]]:
    result = _get_json(
        DEEPSEEK_MODELS_URL,
        {
            "Authorization": f"Bearer {deepseek_api_key()}",
            "Accept": "application/json",
        },
    )
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result.get("data") or []:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id or model_id in seen or not _MODEL_NAME.fullmatch(model_id):
            continue
        if "vision" in model_id.lower():
            continue
        seen.add(model_id)
        rows.append(
            {
                "id": model_id,
                "label": _pretty_deepseek_label(model_id),
                "provider": "deepseek",
            }
        )
    rows.sort(key=lambda row: str(row["id"]))
    if not rows:
        raise ProviderError("DeepSeek returned no models")
    return rows


def _gemini_sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    model_id = str(row.get("id") or "")
    experimental = 1 if re.search(r"(preview|exp|latest)", model_id, re.I) else 0
    dated = 1 if re.search(r"\d{2,4}-\d{2}", model_id) else 0
    return (experimental, dated, model_id)


def list_gemini_models() -> list[dict[str, Any]]:
    key = gemini_api_key()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_token = ""
    for _ in range(8):
        query = {"pageSize": "1000"}
        if page_token:
            query["pageToken"] = page_token
        url = f"{GEMINI_HOST}/models?{urllib.parse.urlencode(query)}"
        result = _get_json(
            url,
            {"Accept": "application/json", "x-goog-api-key": key},
        )
        for item in result.get("models") or []:
            if not isinstance(item, dict):
                continue
            methods = item.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            name = str(item.get("name") or "")
            model_id = name.removeprefix("models/").strip()
            if (
                not model_id
                or model_id in seen
                or not model_id.lower().startswith("gemini")
                or not _MODEL_NAME.fullmatch(model_id)
                or _SKIP_GEMINI.search(model_id)
            ):
                continue
            seen.add(model_id)
            display = str(item.get("displayName") or "").strip() or model_id
            description = str(item.get("description") or "").strip()
            row: dict[str, Any] = {
                "id": model_id,
                "label": display,
                "provider": "gemini",
            }
            if description:
                row["description"] = description[:240]
            if item.get("thinking") is True:
                row["thinking"] = True
            rows.append(row)
        page_token = str(result.get("nextPageToken") or "")
        if not page_token:
            break
    rows.sort(key=_gemini_sort_key)
    if not rows:
        raise ProviderError("Gemini returned no generateContent models")
    return rows


def list_available_models(*, refresh: bool = False) -> dict[str, Any]:
    global _catalog_cache
    now = time.monotonic()
    with _catalog_lock:
        cached = _catalog_cache
        if not refresh and cached and now - cached[0] < _CATALOG_TTL_SEC:
            return cached[1]

    errors: dict[str, str] = {}
    catalog: list[dict[str, Any]] = []

    def _deepseek() -> list[dict[str, Any]]:
        return list_deepseek_models()

    def _gemini() -> list[dict[str, Any]]:
        return list_gemini_models()

    with ThreadPoolExecutor(max_workers=2) as pool:
        deepseek_future = pool.submit(_deepseek)
        gemini_future = pool.submit(_gemini)
        try:
            catalog.extend(deepseek_future.result())
        except Exception as exc:
            errors["deepseek"] = str(exc)
        try:
            catalog.extend(gemini_future.result())
        except Exception as exc:
            errors["gemini"] = str(exc)

    payload = {
        "models": catalog,
        "errors": errors,
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "counts": {
            "deepseek": sum(1 for row in catalog if row.get("provider") == "deepseek"),
            "gemini": sum(1 for row in catalog if row.get("provider") == "gemini"),
        },
    }
    with _catalog_lock:
        _catalog_cache = (time.monotonic(), payload)
    return payload


def clear_model_catalog_cache() -> None:
    global _catalog_cache
    with _catalog_lock:
        _catalog_cache = None
