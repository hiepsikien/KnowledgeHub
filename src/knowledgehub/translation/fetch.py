from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from ..catalog import get_work
from ..grotius_extract import extract_english_treatise
from ..paths import corpus_root

GUTENBERG_TXT = "https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt"


class FetchError(Exception):
    pass


def _raw_path(work: dict) -> Path:
    rel = work.get("content_file") or ""
    if not rel:
        raise FetchError("Work has no content_file")
    return corpus_root() / rel


def fetch_grotius_freedom_of_seas(work_id: str = "grotius--freedom_of_the_seas") -> dict:
    work = get_work(work_id)
    gid = work.get("gutenberg_id")
    if not gid:
        raise FetchError(f"{work_id} has no gutenberg_id")
    url = GUTENBERG_TXT.format(gid=gid)
    with urllib.request.urlopen(url, timeout=120) as resp:
        raw_pg = resp.read().decode("utf-8", errors="replace")
    english, stats = extract_english_treatise(raw_pg)
    dest = _raw_path(work)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(english, encoding="utf-8")
    return {
        "work_id": work_id,
        "source_url": url,
        "dest": str(dest.relative_to(corpus_root())),
        "fetch": stats,
    }


def fetch_raw(work_id: str) -> dict:
    if work_id == "grotius--freedom_of_the_seas":
        return fetch_grotius_freedom_of_seas(work_id)
    raise FetchError(f"No fetch handler for {work_id}")


def fetch_raw_json(work_id: str) -> str:
    return json.dumps(fetch_raw(work_id), ensure_ascii=False, indent=2)
