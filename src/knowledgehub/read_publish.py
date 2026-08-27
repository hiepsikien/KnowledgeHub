from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .catalog import get_work, resolve_content_path
from .normalize import normalize_manuscript
from .paths import corpus_root


class PublishError(RuntimeError):
    pass


def _payload(work: dict[str, Any], text: str) -> dict[str, Any]:
    read = work.get("read") or {}
    rights = work.get("rights") or {}
    return {
        "hub_work_id": work["id"],
        "hub_version": int(work.get("version") or 1),
        "hub_content_hash": work.get("content_hash"),
        "title": work["title"],
        "description": work.get("description") or work["title"],
        "language": work.get("language") or "en",
        "license": work.get("license"),
        "source_url": work.get("source_url") or "",
        "category_slug": read.get("category_slug") or "essays",
        "price_cents": int(read.get("price_cents") or 0),
        "split_length": read.get("split_length") or "standard",
        "status": "pending_review",
        "hub_license_snapshot": {
            "license": work.get("license"),
            "license_source": work.get("license_source"),
            "rights": rights,
        },
        "raw_text": text,
    }


def prepare_publish(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)
    consumers = ((work.get("rights") or {}).get("consumers") or {})
    if consumers.get("read") != "allowed":
        raise PublishError(
            f"{work_id} is not allowed for Read (rights.consumers.read != allowed)"
        )
    path = resolve_content_path(work, root=root)
    if not path.is_file():
        raise PublishError(f"missing manuscript: {path}")
    if not work.get("content_hash"):
        raise PublishError(f"{work_id} has no content_hash — run: knowledgehub hash")
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        text, report = normalize_manuscript(raw, language=str(work.get("language") or "en"))
    except ValueError as exc:
        raise PublishError(str(exc)) from exc
    payload = _payload(work, text)
    payload["_normalize"] = report
    return payload


def preview_normalized(
    work_id: str,
    *,
    corpus: Path | None = None,
    full: bool = False,
    head_chars: int = 12000,
    tail_chars: int = 2500,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)
    path = resolve_content_path(work, root=root)
    if not path.is_file():
        raise PublishError(f"missing manuscript: {path}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        text, report = normalize_manuscript(raw, language=str(work.get("language") or "en"))
    except ValueError as exc:
        raise PublishError(str(exc)) from exc
    truncated = (not full) and len(text) > head_chars + tail_chars
    out: dict[str, Any] = {
        "id": work["id"],
        "title": work.get("title"),
        "normalize": report,
        "truncated": truncated,
    }
    if truncated:
        out["head"] = text[:head_chars]
        out["tail"] = text[-tail_chars:]
    else:
        out["text"] = text
    return out


def _read_body(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if not k.startswith("_")}


def publish_to_read(
    work_id: str,
    *,
    corpus: Path | None = None,
    api_url: str | None = None,
    token: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    payload = prepare_publish(work_id, corpus=corpus)
    report = payload.get("_normalize") or {}
    body = _read_body(payload)
    if dry_run:
        preview = dict(body)
        preview["raw_text"] = f"<{len(body['raw_text'])} chars>"
        return {"dry_run": True, "normalize": report, "payload": preview}

    base = (api_url or os.environ.get("READ_API_URL") or "http://127.0.0.1:8000").rstrip("/")
    secret = token or os.environ.get("READ_HUB_TOKEN") or ""
    if not secret:
        raise PublishError("Set READ_HUB_TOKEN (same value as Read HUB_SYNC_TOKEN)")

    req = urllib.request.Request(
        f"{base}/api/internal/hub/works",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Hub-Sync-Token": secret,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PublishError(f"Read {exc.code}: {detail}") from exc
