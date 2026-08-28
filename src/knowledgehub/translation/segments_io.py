from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..jsonfile import write_json_atomic
from .paths import safe_chapter, segments_dir


def segment_path(source_work_id: str, chapter: str) -> Path:
    ch = safe_chapter(chapter).lower()
    return segments_dir(source_work_id) / f"ch{ch}.json"


def load_segment(source_work_id: str, chapter: str) -> tuple[Path, dict[str, Any]]:
    path = segment_path(source_work_id, chapter)
    if not path.is_file():
        raise FileNotFoundError(f"Segment not found: {path}")
    return path, json.loads(path.read_text(encoding="utf-8"))


def save_segment(path: Path, segment: dict[str, Any]) -> None:
    write_json_atomic(path, segment)


def final_text(segment: dict[str, Any], project: dict[str, Any]) -> str:
    text = segment.get("final")
    if text:
        return str(text)
    mode = project.get("translation_mode")
    if mode:
        draft = (segment.get("drafts") or {}).get(mode)
        if draft:
            return str(draft)
    raise ValueError("Segment has no final translation")
