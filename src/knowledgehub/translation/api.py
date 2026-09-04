from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..paths import corpus_root
from ..settings import MODE_OPTIONS, translation_pipeline
from .annotate import annotate_segment
from .assemble import chapter_sort_key, segment_files, translation_status
from .draft import draft_chapter
from .jobs import (
    cancel_jobs,
    enqueue_job,
    enqueue_missing_drafts,
    list_jobs,
    recent_job_log,
    worker_alive,
    worker_status,
)
from .estimate import missing_draft_preview
from .parts import completeness_status
from .paths import annotations_file, translation_catalog_id
from .project import init_translation_project, list_project_ids, load_project, translation_project_ready
from .promote import promote_translation
from .qa import qa_segment, approve_qa_issues, reopen_qa_issues
from .segments_io import final_text, load_segment
from .titles import display_title_vi


def _list_project_ids() -> list[str]:
    return list_project_ids()


def _segment_files(source_work_id: str) -> list[Path]:
    return segment_files(source_work_id)


def _chapter_summary(source_work_id: str, path: Path, project: dict[str, Any]) -> dict[str, Any]:
    segment = json.loads(path.read_text(encoding="utf-8"))
    chapter = str(segment.get("chapter") or path.stem.removeprefix("ch").upper())
    qa = segment.get("qa") or {}
    scores = qa.get("scores") or {}
    issues = qa.get("issues") or []
    mode = str(project.get("translation_mode") or "")
    raw = ""
    if mode:
        raw = str((segment.get("draft_raw") or {}).get(mode) or "").strip()
    elif isinstance(segment.get("draft_raw"), dict):
        raw = next((str(v).strip() for v in segment["draft_raw"].values() if str(v or "").strip()), "")
    completeness = completeness_status(segment, mode=mode)
    parts = segment.get("parts") if isinstance(segment.get("parts"), list) else []
    return {
        "chapter": chapter,
        "file": str(path.relative_to(corpus_root())),
        "status": segment.get("status"),
        "words": segment.get("words"),
        "has_final": completeness == "ok",
        "has_draft_raw": bool(raw),
        "polish_pending": completeness == "polish_pending",
        "completeness": completeness,
        "part_count": len(parts),
        "parts_ready": sum(1 for part in parts if str(part.get("final") or "").strip()),
        "qa_overall": scores.get("overall"),
        "qa_completed_at": qa.get("completed_at"),
        "issue_count": len(issues),
        "open_issue_count": sum(1 for issue in issues if not issue.get("approved")),
        "annotation_count": 0,
        "annotations_generated_at": segment.get("annotations_generated_at"),
        "title": segment.get("ref_title") or segment.get("title"),
        "title_vi": display_title_vi(segment),
    }


def _artifact_clears_job_error(row: dict[str, Any], job: dict[str, Any]) -> bool:
    """Hide a failed/interrupted job when a later corpus artifact already succeeded."""
    kind = str(job.get("kind") or "")
    finished = str(job.get("finished_at") or job.get("created_at") or "")
    if kind == "qa":
        done_at = str(row.get("qa_completed_at") or "")
        return bool(done_at and finished and done_at >= finished)
    if kind == "annotate":
        done_at = str(row.get("annotations_generated_at") or "")
        return bool(done_at and finished and done_at >= finished)
    if kind == "draft" and job.get("status") == "interrupted" and row.get("has_final"):
        return True
    return False


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
            if completeness_status(seg, mode=str(project.get("translation_mode") or "")) == "ok":
                with_final += 1
            if (seg.get("qa") or {}).get("scores"):
                with_qa += 1
        mode = project.get("translation_mode")
        mode_meta = next((item for item in MODE_OPTIONS if item["id"] == mode), None)
        rows.append(
            {
                "source_work_id": work_id,
                "translation_work_id": translation_catalog_id(
                    work_id, str(project.get("target_language") or "vi")
                ),
                "target_language": project.get("target_language"),
                "translation_mode": mode,
                "mode_label": (mode_meta or {}).get("label") or mode,
                "status": project.get("status"),
                "source_title": (project.get("source") or {}).get("title"),
                "chapters_total": len(chapters),
                "chapters_with_final": with_final,
                "chapters_with_qa": with_qa,
                "ready_to_promote": bool(chapters) and with_final == len(chapters),
                "updated_at": project.get("updated_at"),
            }
        )
    rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    pipe = translation_pipeline()
    return {
        "projects": rows,
        "total": len(rows),
        "modes": list(MODE_OPTIONS),
        "default_mode": pipe.get("default_mode") or "normal",
    }


def get_translation_project(source_work_id: str) -> dict[str, Any]:
    if not translation_project_ready(source_work_id):
        raise FileNotFoundError(f"No translation project: {source_work_id}")
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
    jobs = list_jobs(source_work_id)
    active: dict[str, list[dict[str, Any]]] = {}
    latest: dict[str, dict[str, Any]] = {}
    for job in jobs:
        key = str(job.get("chapter") or "").upper()
        if not key:
            continue
        status = str(job.get("status") or "")
        if status in {"queued", "running"}:
            active.setdefault(key, []).append(job)
            recency = 2
        elif status in {"done", "cancelled"}:
            recency = 1
        else:
            recency = 0
        stamp = (
            str(job.get("created_at") or ""),
            recency,
            str(job.get("finished_at") or job.get("heartbeat_at") or ""),
            str(job.get("id") or ""),
        )
        current = latest.get(key)
        current_status = str((current or {}).get("status") or "")
        if current_status in {"queued", "running"}:
            current_recency = 2
        elif current_status in {"done", "cancelled"}:
            current_recency = 1
        else:
            current_recency = 0
        current_stamp = (
            str((current or {}).get("created_at") or ""),
            current_recency,
            str((current or {}).get("finished_at") or (current or {}).get("heartbeat_at") or ""),
            str((current or {}).get("id") or ""),
        )
        if current is None or stamp >= current_stamp:
            latest[key] = job
    last_error: dict[str, str] = {}
    last_error_kind: dict[str, str] = {}
    last_error_status: dict[str, str] = {}
    for key, job in latest.items():
        if job.get("status") not in {"error", "interrupted"}:
            continue
        last_error[key] = str(job.get("error") or "")
        last_error_kind[key] = str(job.get("kind") or "")
        last_error_status[key] = str(job.get("status") or "")
    for row in chapters:
        chapter = str(row["chapter"]).upper()
        row["jobs"] = active.get(chapter, [])
        job = latest.get(chapter)
        if last_error.get(chapter) and job and not _artifact_clears_job_error(row, job):
            row["last_error"] = last_error[chapter]
            if last_error_kind.get(chapter):
                row["last_error_kind"] = last_error_kind[chapter]
            if last_error_status.get(chapter):
                row["last_error_status"] = last_error_status[chapter]
    status = translation_status(source_work_id)
    pipe = translation_pipeline()
    return {
        "project": project,
        "chapters": chapters,
        "annotations_total": ann_count,
        "translation_work_id": translation_catalog_id(
            source_work_id, str(project.get("target_language") or "vi")
        ),
        "ready_to_promote": status["complete"],
        "missing_chapters": status["missing"],
        "missing_preview": missing_draft_preview(
            chapters,
            auto_annotate=bool(pipe.get("auto_annotate")),
            auto_qa=bool(pipe.get("auto_qa")),
        ),
        "jobs": jobs,
        "log": recent_job_log(),
        "worker_alive": worker_alive(),
        "workers": worker_status(),
        "pipeline": pipe,
    }


def get_segment_detail(source_work_id: str, chapter: str, *, include_drafts: bool = False) -> dict[str, Any]:
    project = load_project(source_work_id)
    path, segment = load_segment(source_work_id, chapter)
    try:
        translation = final_text(segment, project)
    except ValueError:
        translation = ""
    mode = str(project.get("translation_mode") or "")
    raw = str((segment.get("draft_raw") or {}).get(mode) or "").strip() if mode else ""
    completeness = completeness_status(segment, mode=mode)
    part_rows = []
    for part in segment.get("parts") or []:
        if not isinstance(part, dict):
            continue
        part_mode_raw = str((part.get("draft_raw") or {}).get(mode) or "").strip() if mode else ""
        part_rows.append(
            {
                "id": part.get("id"),
                "words": part.get("words"),
                "source_text": part.get("source_text") or "",
                "draft_raw_text": part_mode_raw,
                "translation": str(part.get("final") or "").strip(),
            }
        )
    payload: dict[str, Any] = {
        "source_work_id": source_work_id,
        "chapter": str(segment.get("chapter") or chapter),
        "segment_id": segment.get("id"),
        "status": segment.get("status"),
        "words": segment.get("words"),
        "source_text": segment.get("source_text") or "",
        "translation": translation,
        "has_draft_raw": bool(raw),
        "draft_raw_text": raw,
        "translation_mode": project.get("translation_mode"),
        "qa": segment.get("qa"),
        "annotations_generated_at": segment.get("annotations_generated_at"),
        "completeness": completeness,
        "has_final": completeness == "ok",
        "parts": part_rows,
        "legacy_final": str(segment.get("legacy_final") or "").strip() or None,
        "legacy_draft_raw": str(segment.get("legacy_draft_raw") or "").strip() or None,
        "title": segment.get("ref_title") or segment.get("title"),
        "title_vi": display_title_vi(segment),
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


def split_translation_parts(source_work_id: str, *, enqueue: bool = True) -> dict[str, Any]:
    from .parts import split_long_chapters

    result = split_long_chapters(source_work_id)
    jobs: list[dict[str, Any]] = []
    if enqueue:
        for row in result.get("chapters") or []:
            jobs.append(enqueue_job(source_work_id, str(row["chapter"]), "draft"))
    result["jobs"] = jobs
    result["enqueued"] = sum(1 for job in jobs if job.get("created"))
    return result


def run_promote(source_work_id: str, *, title: str | None = None) -> dict[str, Any]:
    return promote_translation(source_work_id, title=title)


def create_translation_project(
    source_work_id: str,
    *,
    mode: str,
    overwrite: bool = False,
    target_language: str = "vi",
) -> dict[str, Any]:
    created = init_translation_project(
        source_work_id,
        target_language=target_language,
        translation_mode=mode,
        overwrite=overwrite,
    )
    detail = get_translation_project(source_work_id)
    return {**detail, "created": True, "paths": created.get("paths")}


def enqueue_translation_job(
    source_work_id: str,
    *,
    kind: str,
    chapter: str | None = None,
    missing: bool = False,
) -> dict[str, Any]:
    if missing:
        if kind != "draft":
            raise ValueError("missing=true is only valid for kind=draft")
        result = enqueue_missing_drafts(source_work_id)
        result["log"] = recent_job_log()
        result["workers"] = worker_status()
        return result
    if not chapter:
        raise ValueError("Provide chapter or missing=true")
    job = enqueue_job(source_work_id, chapter, kind)
    return {
        "job": job,
        "enqueued": 1 if job.get("created") else 0,
        "log": recent_job_log(),
        "workers": worker_status(),
    }


def cancel_translation_jobs(
    source_work_id: str,
    *,
    job_id: str | None = None,
    chapter: str | None = None,
) -> dict[str, Any]:
    result = cancel_jobs(source_work_id=source_work_id, chapter=chapter, job_id=job_id)
    result["log"] = recent_job_log()
    result["workers"] = worker_status()
    return result
