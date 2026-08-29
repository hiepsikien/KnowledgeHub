from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ref_schema import REF_PARSER_VERSION


def edition_cache_dir(work_id: str, raw_hash: str, *, corpus: Path) -> Path:
    safe_id = work_id.replace("/", "_")
    safe_hash = raw_hash.replace("/", "_")[:64]
    return corpus / "editions" / safe_id / safe_hash


def _cache_meta_path(root: Path) -> Path:
    return root / "cache_meta.json"


def _read_cache_meta(root: Path) -> dict[str, Any] | None:
    path = _cache_meta_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _cache_meta_current(root: Path, *, llm_relabel: bool) -> bool:
    meta = _read_cache_meta(root)
    if not meta or meta.get("ref_parser_version") != REF_PARSER_VERSION:
        return False
    cached_llm = bool(meta.get("llm_relabel"))
    return cached_llm == llm_relabel


def load_cached_edition(
    work_id: str,
    raw_hash: str,
    *,
    corpus: Path,
    llm_relabel: bool = False,
) -> dict[str, Any] | None:
    root = edition_cache_dir(work_id, raw_hash, corpus=corpus)
    path = root / "blocks.json"
    if not path.is_file():
        return None
    if not _cache_meta_current(root, llm_relabel=llm_relabel):
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
    llm_relabel: bool = False,
) -> Path:
    root = edition_cache_dir(work_id, raw_hash, corpus=corpus)
    root.mkdir(parents=True, exist_ok=True)
    (root / "blocks.json").write_text(
        json.dumps(edition, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _cache_meta_path(root).write_text(
        json.dumps(
            {"ref_parser_version": REF_PARSER_VERSION, "llm_relabel": llm_relabel},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
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
