from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..paths import corpus_root
from .annotate import annotate_segment
from .draft import draft_chapter
from .paths import annotations_file, segments_dir
from .project import load_project
from .qa import qa_segment
from .segments_io import final_text, load_segment

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


def _chapter_sort_key(chapter: str) -> tuple[int, str]:
    key = chapter.strip().lower()
    return (_ROMAN.get(key, 999), chapter)


def _list_project_ids() -> list[str]:
    root = corpus_root() / "translations"
    if not root.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and (path / "project.json").is_file():
            ids.append(path.name)
    return ids


def _segment_files(source_work_id: str) -> list[Path]:
    seg_dir = segments_dir(source_work_id)
    if not seg_dir.is_dir():
        return []
    return sorted(
        (p for p in seg_dir.glob("ch*.json") if not p.name.endswith("-sample.json")),
        key=lambda p: _chapter_sort_key(p.stem.removeprefix("ch")),
    )


def _chapter_summary(source_work_id: str, path: Path, project: dict[str, Any]) -> dict[str, Any]:
    segment = json.loads(path.read_text(encoding="utf-8"))
    chapter = str(segment.get("chapter") or path.stem.removeprefix("ch").upper())
    final = segment.get("final") or ""
    qa = segment.get("qa") or {}
    scores = qa.get("scores") or {}
    return {
        "chapter": chapter,
        "file": str(path.relative_to(corpus_root())),
        "status": segment.get("status"),
        "words": segment.get("words"),
        "has_final": bool(str(final).strip()),
        "qa_overall": scores.get("overall"),
        "qa_completed_at": qa.get("completed_at"),
        "issue_count": len(qa.get("issues") or []),
        "annotations_generated_at": segment.get("annotations_generated_at"),
    }


def list_translation_projects() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for work_id in _list_project_ids():
        try:
            project = load_project(work_id)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            continue
        chapters = _segment_files(work_id)
        with_final = 0
        with_qa = 0
        for path in chapters:
            seg = json.loads(path.read_text(encoding="utf-8"))
            if str(seg.get("final") or "").strip():
                with_final += 1
            if (seg.get("qa") or {}).get("scores"):
                with_qa += 1
        rows.append(
            {
                "source_work_id": work_id,
                "translation_work_id": project.get("translation_work_id"),
                "target_language": project.get("target_language"),
                "translation_mode": project.get("translation_mode"),
                "status": project.get("status"),
                "source_title": (project.get("source") or {}).get("title"),
                "chapters_total": len(chapters),
                "chapters_with_final": with_final,
                "chapters_with_qa": with_qa,
                "updated_at": project.get("updated_at"),
            }
        )
    return {"projects": rows, "total": len(rows)}


def get_translation_project(source_work_id: str) -> dict[str, Any]:
    project = load_project(source_work_id)
    chapters = [
        _chapter_summary(source_work_id, path, project) for path in _segment_files(source_work_id)
    ]
    ann_path = annotations_file(source_work_id)
    ann_count = 0
    if ann_path.is_file():
        store = json.loads(ann_path.read_text(encoding="utf-8"))
        ann_count = len(store.get("annotations") or [])
    return {
        "project": project,
        "chapters": chapters,
        "annotations_total": ann_count,
    }


def get_segment_detail(source_work_id: str, chapter: str, *, include_drafts: bool = False) -> dict[str, Any]:
    project = load_project(source_work_id)
    path, segment = load_segment(source_work_id, chapter)
    try:
        translation = final_text(segment, project)
    except ValueError:
        translation = ""
    payload: dict[str, Any] = {
        "source_work_id": source_work_id,
        "chapter": str(segment.get("chapter") or chapter),
        "segment_id": segment.get("id"),
        "status": segment.get("status"),
        "words": segment.get("words"),
        "source_text": segment.get("source_text") or "",
        "translation": translation,
        "translation_mode": project.get("translation_mode"),
        "qa": segment.get("qa"),
        "annotations_generated_at": segment.get("annotations_generated_at"),
        "file": str(path.relative_to(corpus_root())),
    }
    if include_drafts:
        payload["drafts"] = segment.get("drafts")
        payload["draft_raw"] = segment.get("draft_raw")
    return payload


def list_annotations(source_work_id: str, chapter: str | None = None) -> dict[str, Any]:
    ann_path = annotations_file(source_work_id)
    if not ann_path.is_file():
        return {"annotations": [], "total": 0}
    store = json.loads(ann_path.read_text(encoding="utf-8"))
    items = store.get("annotations") or []
    if chapter:
        ch = chapter.strip().upper()
        items = [a for a in items if str(a.get("chapter", "")).upper() == ch]
    items = sorted(
        items,
        key=lambda a: (
            _chapter_sort_key(str(a.get("chapter", ""))),
            str(a.get("marker") or ""),
            str(a.get("id") or ""),
        ),
    )
    return {"annotations": items, "total": len(items), "updated_at": store.get("updated_at")}


def run_qa(source_work_id: str, chapter: str) -> dict[str, Any]:
    return qa_segment(source_work_id, chapter)


def run_annotate(source_work_id: str, chapter: str) -> dict[str, Any]:
    return annotate_segment(source_work_id, chapter)


def run_draft(source_work_id: str, chapter: str) -> dict[str, Any]:
    return draft_chapter(source_work_id, chapter=chapter)
