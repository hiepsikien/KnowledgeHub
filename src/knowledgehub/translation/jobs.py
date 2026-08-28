"""File-backed translation job queue with a single background worker."""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..paths import corpus_root
from .paths import safe_chapter, safe_work_id

KINDS = ("draft", "qa", "annotate")
ACTIVE = frozenset({"queued", "running"})

_lock = threading.Lock()
_wake = threading.Event()
_stop: threading.Event | None = None
_thread: threading.Thread | None = None


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def worker_enabled() -> bool:
    flag = (os.environ.get("KNOWLEDGEHUB_JOB_WORKER") or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def jobs_path() -> Path:
    return corpus_root() / ".translation-jobs.json"


def worker_alive() -> bool:
    return bool(_thread and _thread.is_alive())


def _empty_store() -> dict[str, Any]:
    return {"jobs": [], "updated_at": _now()}


def _read_store() -> dict[str, Any]:
    path = jobs_path()
    if not path.is_file():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        data["jobs"] = []
    return data


def _write_store(store: dict[str, Any]) -> None:
    jobs = list(store.get("jobs") or [])
    active = [job for job in jobs if job.get("status") in ACTIVE]
    done = [job for job in jobs if job.get("status") not in ACTIVE]
    store["jobs"] = active + done[-40:]
    store["updated_at"] = _now()
    path = jobs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _public(job: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "work_id",
        "chapter",
        "kind",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "error",
        "result",
        "duplicate_of",
    )
    return {key: job.get(key) for key in keys if job.get(key) is not None}


def list_jobs(source_work_id: str | None = None) -> list[dict[str, Any]]:
    work_id = safe_work_id(source_work_id) if source_work_id else None
    with _lock:
        jobs = list(_read_store().get("jobs") or [])
    if work_id:
        jobs = [job for job in jobs if job.get("work_id") == work_id]
    return [_public(job) for job in reversed(jobs)]


def _find_active(jobs: list[dict[str, Any]], work_id: str, chapter: str, kind: str) -> dict[str, Any] | None:
    for job in jobs:
        if (
            job.get("status") in ACTIVE
            and job.get("work_id") == work_id
            and job.get("chapter") == chapter
            and job.get("kind") == kind
        ):
            return job
    return None


def enqueue_job(source_work_id: str, chapter: str, kind: str) -> dict[str, Any]:
    from .project import load_project
    from .segments_io import load_segment

    work_id = safe_work_id(source_work_id)
    ch = safe_chapter(chapter).upper()
    if kind not in KINDS:
        raise ValueError(f"Unknown job kind: {kind!r}")
    load_project(work_id)
    load_segment(work_id, ch)
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        existing = _find_active(jobs, work_id, ch, kind)
        if existing:
            payload = _public(existing)
            payload["created"] = False
            return payload
        job = {
            "id": secrets.token_hex(8),
            "work_id": work_id,
            "chapter": ch,
            "kind": kind,
            "status": "queued",
            "created_at": _now(),
        }
        jobs.append(job)
        store["jobs"] = jobs
        _write_store(store)
    _wake.set()
    payload = _public(job)
    payload["created"] = True
    return payload


def enqueue_missing_drafts(source_work_id: str) -> dict[str, Any]:
    from .assemble import translation_status

    work_id = safe_work_id(source_work_id)
    missing = translation_status(work_id)["missing"]
    jobs: list[dict[str, Any]] = []
    for chapter in missing:
        jobs.append(enqueue_job(work_id, chapter, "draft"))
    return {
        "work_id": work_id,
        "kind": "draft",
        "enqueued": sum(1 for job in jobs if job.get("created")),
        "jobs": jobs,
        "missing": missing,
    }


def requeue_stale_running() -> int:
    n = 0
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        for job in jobs:
            if job.get("status") == "running":
                job["status"] = "queued"
                job.pop("started_at", None)
                n += 1
        if n:
            store["jobs"] = jobs
            _write_store(store)
    return n


def claim_next() -> dict[str, Any] | None:
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        for job in jobs:
            if job.get("status") != "queued":
                continue
            job["status"] = "running"
            job["started_at"] = _now()
            store["jobs"] = jobs
            _write_store(store)
            return dict(job)
    return None


def complete_job(job_id: str, *, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        for job in jobs:
            if job.get("id") != job_id:
                continue
            job["status"] = "error" if error else "done"
            job["finished_at"] = _now()
            if error:
                job["error"] = error
                job.pop("result", None)
            else:
                job.pop("error", None)
                if result is not None:
                    job["result"] = result
            break
        store["jobs"] = jobs
        _write_store(store)


def execute_job(job: dict[str, Any]) -> dict[str, Any]:
    from .annotate import annotate_segment
    from .draft import draft_chapter
    from .qa import qa_segment

    kind = job["kind"]
    work_id = job["work_id"]
    chapter = job["chapter"]
    if kind == "draft":
        return draft_chapter(work_id, chapter=chapter)
    if kind == "qa":
        return qa_segment(work_id, chapter)
    if kind == "annotate":
        return annotate_segment(work_id, chapter)
    raise ValueError(f"Unknown job kind: {kind!r}")


def _enqueue_followups(job: dict[str, Any]) -> list[dict[str, Any]]:
    from ..settings import followup_kinds

    queued: list[dict[str, Any]] = []
    for kind in followup_kinds(str(job.get("kind") or "")):
        queued.append(enqueue_job(job["work_id"], job["chapter"], kind))
    return queued


def process_next_job() -> dict[str, Any] | None:
    job = claim_next()
    if not job:
        return None
    try:
        result = execute_job(job)
        complete_job(job["id"], result=result)
        job["status"] = "done"
        job["result"] = result
        _enqueue_followups(job)
    except Exception as exc:
        complete_job(job["id"], error=str(exc))
        job["status"] = "error"
        job["error"] = str(exc)
    return job


def worker_loop(stop: threading.Event) -> None:
    requeue_stale_running()
    while not stop.is_set():
        job = process_next_job()
        if job is None:
            _wake.wait(timeout=0.75)
            _wake.clear()


def start_worker() -> None:
    global _stop, _thread
    if not worker_enabled():
        return
    if _thread and _thread.is_alive():
        return
    _stop = threading.Event()
    _wake.clear()
    _thread = threading.Thread(target=worker_loop, args=(_stop,), name="kh-translate-worker", daemon=True)
    _thread.start()


def stop_worker() -> None:
    global _stop, _thread
    if _stop is not None:
        _stop.set()
        _wake.set()
    thread = _thread
    if thread and thread.is_alive():
        thread.join(timeout=2.0)
    _thread = None
    _stop = None
