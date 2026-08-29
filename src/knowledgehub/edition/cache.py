from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def edition_cache_dir(work_id: str, raw_hash: str, *, corpus: Path) -> Path:
    safe_id = work_id.replace("/", "_")
    safe_hash = raw_hash.replace("/", "_")[:64]
    return corpus / "editions" / safe_id / safe_hash


def load_cached_edition(work_id: str, raw_hash: str, *, corpus: Path) -> dict[str, Any] | None:
    path = edition_cache_dir(work_id, raw_hash, corpus=corpus) / "blocks.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_cached_edition(
    work_id: str,
    raw_hash: str,
    edition: dict[str, Any],
    *,
    corpus: Path,
    report: dict[str, Any] | None = None,
) -> Path:
    root = edition_cache_dir(work_id, raw_hash, corpus=corpus)
    root.mkdir(parents=True, exist_ok=True)
    (root / "blocks.json").write_text(
        json.dumps(edition, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if report is not None:
        (root / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    md = str(edition.get("reading_markdown") or "")
    if md:
        (root / "reading.md").write_text(md + "\n", encoding="utf-8")
    return root
