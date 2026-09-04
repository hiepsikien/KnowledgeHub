"""Join chapter finals into a reading manuscript. Does not write raw/."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .parts import completeness_status
from .paths import segments_dir
from .project import load_project
from .segments_io import final_text

_ROMAN = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
    "xiii": 13,
    "xiv": 14,
    "xv": 15,
}
_NAMED = {
    "preface": 0,
    "foreword": 0,
    "introduction": 0,
    "prologue": 0,
    "epilogue": 10_000,
    "appendix": 10_001,
}
_COMPACT_CHAPTER = re.compile(r"^(?:chapter|chap)?([ivxlc]+|\d+)$")


class IncompleteTranslation(ValueError):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(
            "Missing final translation for chapters: " + ", ".join(missing)
        )


def chapter_sort_key(chapter: str) -> tuple[int, str]:
    key = chapter.strip().lower()
    compact = re.sub(r"[^a-z0-9]", "", key)
    if key.isdigit() or compact.isdigit():
        return (int(compact or key), chapter)
    if key in _NAMED:
        return (_NAMED[key], chapter)
    if compact in _NAMED:
        return (_NAMED[compact], chapter)
    match = _COMPACT_CHAPTER.fullmatch(compact)
    if match:
        token = match.group(1)
        if token.isdigit():
            return (int(token), chapter)
        if token in _ROMAN:
            return (_ROMAN[token], chapter)
    if compact.startswith("catalogue") or compact.startswith("catalog"):
        return (10_002, compact)
    if compact.startswith("bibliograph"):
        return (10_003, compact)
    if compact.startswith("glossary"):
        return (10_004, compact)
    return (_ROMAN.get(key, 999), compact or chapter)


def segment_files(source_work_id: str) -> list[Path]:
    seg_dir = segments_dir(source_work_id)
    if not seg_dir.is_dir():
        return []
    return sorted(
        (p for p in seg_dir.glob("ch*.json") if not p.name.endswith("-sample.json")),
        key=lambda p: chapter_sort_key(p.stem.removeprefix("ch")),
    )


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def translation_status(source_work_id: str) -> dict[str, Any]:
    files = segment_files(source_work_id)
    missing: list[str] = []
    ready: list[str] = []
    for path in files:
        segment = json.loads(path.read_text(encoding="utf-8"))
        chapter = str(segment.get("chapter") or path.stem.removeprefix("ch").upper())
        if completeness_status(segment) == "ok":
            ready.append(chapter)
        else:
            missing.append(chapter)
    return {
        "chapters_total": len(files),
        "chapters_ready": len(ready),
        "missing": missing,
        "complete": bool(files) and not missing,
    }


def chapter_finals(source_work_id: str) -> dict[str, str]:
    """Chapter id → Vietnamese final, for publish-time note filtering."""
    project = load_project(source_work_id)
    texts: dict[str, str] = {}
    for path in segment_files(source_work_id):
        segment = json.loads(path.read_text(encoding="utf-8"))
        chapter = str(segment.get("chapter") or path.stem.removeprefix("ch").upper())
        try:
            text = final_text(segment, project)
        except ValueError:
            continue
        texts[chapter] = text
        texts[chapter.upper()] = text
        texts[chapter.lower()] = text
    return texts


def assemble_finals(
    source_work_id: str,
    *,
    require_complete: bool = True,
) -> tuple[str, dict[str, Any]]:
    project = load_project(source_work_id)
    files = segment_files(source_work_id)
    if not files:
        raise ValueError(f"No chapter segments for {source_work_id}")
    parts: list[str] = []
    missing: list[str] = []
    for path in files:
        segment = json.loads(path.read_text(encoding="utf-8"))
        chapter = str(segment.get("chapter") or path.stem.removeprefix("ch").upper())
        if completeness_status(segment) != "ok":
            missing.append(chapter)
            continue
        try:
            parts.append(final_text(segment, project).strip())
        except ValueError:
            missing.append(chapter)
    if missing and require_complete:
        raise IncompleteTranslation(missing)
    text = "\n\n".join(p for p in parts if p).strip() + "\n"
    meta = {
        "source_work_id": source_work_id,
        "chapters": len(parts),
        "missing": missing,
        "chars": len(text),
        "content_hash": hash_text(text),
    }
    return text, meta
