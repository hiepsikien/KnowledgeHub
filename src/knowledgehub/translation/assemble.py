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

_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
_NAMED = {
    "preface": 0,
    "foreword": 0,
    "introduction": 0,
    "prologue": 0,
    "epilogue": 10_000,
    "appendix": 10_001,
}
_COMPACT_CHAPTER = re.compile(r"^(?:chapter|chap)?([ivxlcdm]+|\d+)$")
_SOURCE_ORDER = re.compile(rb'"source_order"\s*:\s*(-?\d+)')
_REF_CHAPTER_ID = re.compile(rb'"ref_chapter_id"\s*:\s*"([^"]+)"')
_SEC_NUM = re.compile(r"sec-(\d+)")


def roman_to_int(token: str) -> int | None:
    text = token.strip().lower()
    if not text or any(ch not in _ROMAN_VALUES for ch in text):
        return None
    total = 0
    prev = 0
    for ch in reversed(text):
        val = _ROMAN_VALUES[ch]
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    return total if total > 0 else None


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
        parsed = roman_to_int(token)
        if parsed is not None:
            return (parsed, chapter)
    if compact.startswith("catalogue") or compact.startswith("catalog"):
        return (10_002, compact)
    if compact.startswith("bibliograph"):
        return (10_003, compact)
    if compact.startswith("glossary"):
        return (10_004, compact)
    return (roman_to_int(key) or roman_to_int(compact) or 999, compact or chapter)


def _ref_section_rank(ref_chapter_id: str) -> int | None:
    sid = ref_chapter_id.strip().lower()
    if not sid:
        return None
    if "front" in sid:
        return -1
    match = _SEC_NUM.search(sid)
    return int(match.group(1)) if match else None


def segment_sort_key(path: Path) -> tuple[int, int, str]:
    """Prefer chế bản order (source_order / ref_chapter_id) over filename slugs."""
    try:
        raw = path.read_bytes()
    except OSError:
        raw = b""
    order = _SOURCE_ORDER.search(raw)
    if order:
        return (0, int(order.group(1)), path.name)
    ref = _REF_CHAPTER_ID.search(raw)
    if ref:
        rank = _ref_section_rank(ref.group(1).decode("utf-8", errors="replace"))
        if rank is not None:
            return (0, rank, path.name)
    n, rest = chapter_sort_key(path.stem.removeprefix("ch"))
    return (1, n, rest)


def segment_files(source_work_id: str) -> list[Path]:
    seg_dir = segments_dir(source_work_id)
    if not seg_dir.is_dir():
        return []
    return sorted(
        (p for p in seg_dir.glob("ch*.json") if not p.name.endswith("-sample.json")),
        key=segment_sort_key,
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
