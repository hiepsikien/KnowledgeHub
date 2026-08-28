from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..paths import corpus_root
from .annotate import annotate_segment
from .assemble import chapter_sort_key, segment_files, translation_status
from .draft import draft_chapter
from .paths import annotations_file, translation_catalog_id
from .project import load_project
from .promote import promote_translation
from .qa import qa_segment, approve_qa_issues, reopen_qa_issues
from .segments_io import final_text, load_segment


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
    return segment_files(source_work_id)


def _chapter_summary(source_work_id: str, path: Path, project: dict[str, Any]) -> dict[str, Any]:
    segment = json.loads(path.read_text(encoding="utf-8"))
    chapter = str(segment.get("chapter") or path.stem.removeprefix("ch").upper())
    final = segment.get("final") or ""
    qa = segment.get("qa") or {}
    scores = qa.get("scores") or {}
    issues = qa.get("issues") or []
    return {
        "chapter": chapter,
        "file": str(path.relative_to(corpus_root())),
        "status": segment.get("status"),
        "words": segment.get("words"),
        "has_final": bool(str(final).strip()),
        "qa_overall": scores.get("overall"),
        "qa_completed_at": qa.get("completed_at"),
        "issue_count": len(issues),
        "open_issue_count": sum(1 for issue in issues if not issue.get("approved")),
        "annotation_count": 0,
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
                "translation_work_id": translation_catalog_id(
                    work_id, str(project.get("target_language") or "vi")
                ),
                "target_language": project.get("target_language"),
                "translation_mode": project.get("translation_mode"),
                "status": project.get("status"),
                "source_title": (project.get("source") or {}).get("title"),
                "chapters_total": len(chapters),
                "chapters_with_final": with_final,
                "chapters_with_qa": with_qa,
                "ready_to_promote": bool(chapters) and with_final == len(chapters),
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
    by_chapter: dict[str, int] = {}
    if ann_path.is_file():
        store = json.loads(ann_path.read_text(encoding="utf-8"))
        items = store.get("annotations") or []
        ann_count = len(items)
        for item in items:
            key = str(item.get("chapter") or "").upper()
            if key:
                by_chapter[key] = by_chapter.get(key, 0) + 1
        for row in chapters:
            row["annotation_count"] = by_chapter.get(str(row["chapter"]).upper(), 0)
    status = translation_status(source_work_id)
    return {
        "project": project,
        "chapters": chapters,
        "annotations_total": ann_count,
        "translation_work_id": translation_catalog_id(
            source_work_id, str(project.get("target_language") or "vi")
        ),
        "ready_to_promote": status["complete"],
        "missing_chapters": status["missing"],
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
            chapter_sort_key(str(a.get("chapter", ""))),
            str(a.get("marker") or ""),
            str(a.get("id") or ""),
        ),
    )
    return {"annotations": items, "total": len(items), "updated_at": store.get("updated_at")}


def run_qa(source_work_id: str, chapter: str) -> dict[str, Any]:
    return qa_segment(source_work_id, chapter)


def run_approve_qa(
    source_work_id: str,
    chapter: str,
    *,
    index: int | None = None,
    replacement: str | None = None,
    replacements: dict[int, str] | None = None,
) -> dict[str, Any]:
    return approve_qa_issues(
        source_work_id,
        chapter,
        index=index,
        replacement=replacement,
        replacements=replacements,
    )


def run_reopen_qa(
    source_work_id: str, chapter: str, *, index: int | None = None
) -> dict[str, Any]:
    return reopen_qa_issues(source_work_id, chapter, index=index)


def run_annotate(source_work_id: str, chapter: str) -> dict[str, Any]:
    return annotate_segment(source_work_id, chapter)


def run_draft(source_work_id: str, chapter: str) -> dict[str, Any]:
    return draft_chapter(source_work_id, chapter=chapter)


def run_promote(source_work_id: str, *, title: str | None = None) -> dict[str, Any]:
    return promote_translation(source_work_id, title=title)
