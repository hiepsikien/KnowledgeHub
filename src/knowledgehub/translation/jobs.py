"""File-backed translation job queue with a scalable background worker pool."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
from collections import deque
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..jsonfile import quarantine_corrupt, write_json_atomic
from ..paths import corpus_root
from .paths import safe_chapter, safe_work_id

KIND_ORDER = ("draft", "annotate", "qa")
KINDS = KIND_ORDER
KIND_RANK = {kind: index for index, kind in enumerate(KIND_ORDER)}
ACTIVE = frozenset({"queued", "running"})
STOPPED = frozenset({"cancelled", "interrupted"})

_lock = threading.Lock()
_pool_lock = threading.Lock()
_wake = threading.Event()
_stop: threading.Event | None = None
_threads: list[threading.Thread] = []
_next_worker = 0
_requeued = False
_cancel_flags: set[str] = set()
_current_job_id: ContextVar[str | None] = ContextVar("kh_job_id", default=None)
_events: deque[dict[str, Any]] = deque(maxlen=80)
log = logging.getLogger("knowledgehub.jobs")


def configure_job_logging() -> None:
    root = logging.getLogger("knowledgehub")
    root.setLevel(logging.INFO)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [kh] %(message)s"))
        root.addHandler(handler)
        root.propagate = False


def job_log_event(event: str, **fields: Any) -> None:
    row: dict[str, Any] = {"at": _now(), "event": event}
    for key, value in fields.items():
        if value is not None:
            row[key] = value
    _events.append(row)
    extra = " ".join(f"{key}={value}" for key, value in row.items() if key not in {"at", "event"})
    log.info("%s %s", event, extra)


def recent_job_log() -> list[dict[str, Any]]:
    return list(_events)


class JobCancelled(Exception):
    """Raised when a running job is cancelled or interrupted."""


class JobGuardError(Exception):
    """Raised when a job hits an attempt or timeout guard."""


HARD_JOB_LIMIT_SEC = 6 * 3600

TRANSIENT_ERROR = re.compile(
    r"HTTP (?:408|409|425|429|500|502|503|504)\b"
    r"|RESOURCE_EXHAUSTED|UNAVAILABLE|high demand|overloaded|temporarily"
    r"|timed out|urlopen error|Connection (?:reset|refused|aborted)|Remote end closed"
    # A model that stopped mid-word is a flake, and finished parts are already
    # checkpointed, so another attempt only redoes the part that failed.
    r"|stopped mid-word|hit max_tokens|hit maxOutputTokens",
    re.I,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _now_plus(seconds: float) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()


def _seconds_since(stamp: Any, now: datetime) -> float | None:
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (now - moment).total_seconds()


def is_transient_error(message: str) -> bool:
    """Provider hiccups worth another attempt, unlike bad input or our own guards."""
    return bool(TRANSIENT_ERROR.search(message or ""))


def retry_delay_for(attempt: int) -> float:
    return min(120.0, 15.0 * max(1, attempt))


def worker_enabled() -> bool:
    flag = (os.environ.get("KNOWLEDGEHUB_JOB_WORKER") or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def jobs_path() -> Path:
    return corpus_root() / ".translation-jobs.json"


def desired_worker_count(queued: int, running: int, min_workers: int, max_workers: int) -> int:
    return max(min_workers, min(max_workers, queued + running))


def worker_alive() -> bool:
    return worker_status()["alive"] > 0


def worker_status() -> dict[str, int]:
    from ..settings import worker_limits

    min_workers, max_workers = worker_limits()
    with _pool_lock:
        alive = sum(1 for thread in _threads if thread.is_alive())
    return {
        "alive": alive,
        "min_workers": min_workers,
        "max_workers": max_workers,
    }


def _queue_depth() -> tuple[int, int]:
    with _lock:
        jobs = list(_read_store().get("jobs") or [])
    queued = sum(1 for job in jobs if job.get("status") == "queued")
    running = sum(1 for job in jobs if job.get("status") == "running")
    return queued, running


def _empty_store() -> dict[str, Any]:
    return {"jobs": [], "updated_at": _now()}


def _discard_corrupt_store(path: Path, reason: str) -> dict[str, Any]:
    moved = quarantine_corrupt(path)
    log.error(
        "translation job store unreadable (%s); queue reset. Saved copy: %s",
        reason,
        moved or "none",
    )
    job_log_event("store_corrupt", reason=reason, backup=moved.name if moved else None)
    return _empty_store()


def _read_store() -> dict[str, Any]:
    path = jobs_path()
    if not path.is_file():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _discard_corrupt_store(path, f"invalid JSON: {exc}")
    except OSError as exc:
        log.error("cannot read translation job store: %s", exc)
        return _empty_store()
    if not isinstance(data, dict):
        return _discard_corrupt_store(path, "top level is not an object")
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
    write_json_atomic(jobs_path(), store)


def _public(job: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "work_id",
        "chapter",
        "kind",
        "status",
        "phase",
        "detail",
        "attempts",
        "heartbeat_at",
        "created_at",
        "started_at",
        "finished_at",
        "not_before",
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
            job_log_event(
                "enqueue_duplicate",
                job_id=existing.get("id"),
                work_id=work_id,
                chapter=ch,
                kind=kind,
                status=existing.get("status"),
            )
            return payload
        job = {
            "id": secrets.token_hex(8),
            "work_id": work_id,
            "chapter": ch,
            "kind": kind,
            "status": "queued",
            "phase": "queued",
            "detail": "Đã xếp hàng",
            "attempts": 0,
            "created_at": _now(),
            "heartbeat_at": _now(),
        }
        jobs.append(job)
        store["jobs"] = jobs
        _write_store(store)
    _wake.set()
    scale_workers()
    payload = _public(job)
    payload["created"] = True
    job_log_event(
        "enqueue",
        job_id=job["id"],
        work_id=work_id,
        chapter=ch,
        kind=kind,
        created=True,
        queued=_queue_depth()[0],
        running=_queue_depth()[1],
        workers=worker_status()["alive"],
    )
    return payload


def enqueue_missing_drafts(source_work_id: str) -> dict[str, Any]:
    from .assemble import translation_status

    work_id = safe_work_id(source_work_id)
    missing = translation_status(work_id)["missing"]
    jobs: list[dict[str, Any]] = []
    job_log_event("enqueue_missing", work_id=work_id, missing=",".join(missing) or "-", count=len(missing))
    for chapter in missing:
        jobs.append(enqueue_job(work_id, chapter, "draft"))
    created = sum(1 for job in jobs if job.get("created"))
    job_log_event(
        "enqueue_missing_done",
        work_id=work_id,
        enqueued=created,
        total=len(jobs),
        queued=_queue_depth()[0],
        running=_queue_depth()[1],
        workers=worker_status()["alive"],
    )
    return {
        "work_id": work_id,
        "kind": "draft",
        "enqueued": created,
        "jobs": jobs,
        "missing": missing,
    }


def interrupt_stale_running() -> int:
    """On worker start, drop in-flight jobs instead of silently retrying (token guard)."""
    n = 0
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        for job in jobs:
            if job.get("status") != "running":
                continue
            job_id = str(job.get("id") or "")
            job["status"] = "interrupted"
            job["phase"] = "interrupted"
            job["detail"] = "Worker restart — không tự chạy lại"
            job["finished_at"] = _now()
            job["heartbeat_at"] = _now()
            job["error"] = "interrupted: worker restarted"
            if job_id:
                _cancel_flags.add(job_id)
            n += 1
        if n:
            store["jobs"] = jobs
            _write_store(store)
            job_log_event("interrupt_stale", count=n)
    return n


def cancel_jobs(
    *,
    source_work_id: str | None = None,
    chapter: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    work_id = safe_work_id(source_work_id) if source_work_id else None
    ch = safe_chapter(chapter).upper() if chapter else None
    cancelled: list[dict[str, Any]] = []
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        for job in jobs:
            if job.get("status") not in ACTIVE:
                continue
            if job_id and job.get("id") != job_id:
                continue
            if work_id and job.get("work_id") != work_id:
                continue
            if ch and str(job.get("chapter") or "").upper() != ch:
                continue
            job["status"] = "cancelled"
            job["phase"] = "cancelled"
            job["detail"] = "Đã hủy"
            job["finished_at"] = _now()
            job["heartbeat_at"] = _now()
            job.pop("error", None)
            _cancel_flags.add(str(job.get("id") or ""))
            cancelled.append(_public(job))
        if cancelled:
            store["jobs"] = jobs
            _write_store(store)
    if cancelled:
        job_log_event(
            "cancel",
            count=len(cancelled),
            work_id=work_id,
            chapter=ch,
            job_id=job_id,
            ids=",".join(str(job.get("id") or "") for job in cancelled),
        )
    return {"cancelled": len(cancelled), "jobs": cancelled}


def update_job_progress(job_id: str, *, phase: str, detail: str | None = None) -> None:
    stamp = _now()
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        for job in jobs:
            if job.get("id") != job_id:
                continue
            if job.get("status") in STOPPED:
                return
            job["phase"] = phase
            if detail is not None:
                job["detail"] = detail
            job["heartbeat_at"] = stamp
            break
        store["jobs"] = jobs
        _write_store(store)


def report_progress(phase: str, detail: str | None = None) -> None:
    job_id = _current_job_id.get()
    if job_id:
        update_job_progress(job_id, phase=phase, detail=detail)


def raise_if_stopped() -> None:
    job_id = _current_job_id.get()
    if not job_id:
        return
    if job_id in _cancel_flags:
        raise JobCancelled("job cancelled")
    from ..settings import job_guard_limits

    _, timeout_sec = job_guard_limits()
    with _lock:
        store = _read_store()
        job = next((row for row in (store.get("jobs") or []) if row.get("id") == job_id), None)
        snapshot = dict(job) if job else {}
    status = snapshot.get("status")
    if status in STOPPED:
        raise JobCancelled(f"job {status}")
    now = datetime.now(UTC)
    stalled = _seconds_since(snapshot.get("heartbeat_at") or snapshot.get("started_at"), now)
    if stalled is not None and stalled > timeout_sec:
        raise JobGuardError(f"no progress for {int(stalled)}s (limit {timeout_sec}s)")
    total = _seconds_since(snapshot.get("started_at"), now)
    if total is not None and total > HARD_JOB_LIMIT_SEC:
        raise JobGuardError(f"job ran {int(total)}s (hard limit {HARD_JOB_LIMIT_SEC}s)")


def claim_next() -> dict[str, Any] | None:
    from ..settings import job_guard_limits

    max_attempts, _timeout = job_guard_limits()
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        busy = {
            (job.get("work_id"), str(job.get("chapter") or "").upper())
            for job in jobs
            if job.get("status") == "running"
        }
        dirty = False
        chosen: dict[str, Any] | None = None
        chosen_rank = len(KIND_ORDER)
        stamp = _now()
        for job in jobs:
            if job.get("status") != "queued":
                continue
            not_before = str(job.get("not_before") or "")
            if not_before and not_before > stamp:
                continue
            key = (job.get("work_id"), str(job.get("chapter") or "").upper())
            if key in busy:
                continue
            if int(job.get("attempts") or 0) >= max_attempts:
                job["status"] = "error"
                job["phase"] = "error"
                job["detail"] = f"Quá số lần thử ({max_attempts})"
                job["error"] = f"max_attempts {max_attempts}"
                job["finished_at"] = _now()
                job["heartbeat_at"] = _now()
                dirty = True
                continue
            rank = KIND_RANK.get(str(job.get("kind") or ""), len(KIND_ORDER))
            if chosen is None or rank < chosen_rank:
                chosen = job
                chosen_rank = rank
                if chosen_rank == 0:
                    break
        if chosen is None:
            if dirty:
                store["jobs"] = jobs
                _write_store(store)
            return None
        chosen["attempts"] = int(chosen.get("attempts") or 0) + 1
        chosen["status"] = "running"
        chosen["phase"] = "starting"
        chosen["detail"] = "Bắt đầu"
        chosen["started_at"] = _now()
        chosen["heartbeat_at"] = _now()
        chosen.pop("not_before", None)
        store["jobs"] = jobs
        _write_store(store)
        job_log_event(
            "claim",
            job_id=chosen.get("id"),
            work_id=chosen.get("work_id"),
            chapter=chosen.get("chapter"),
            kind=chosen.get("kind"),
            attempts=chosen.get("attempts"),
            thread=threading.current_thread().name,
        )
        return dict(chosen)


def complete_job(
    job_id: str,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    status: str | None = None,
) -> None:
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        for job in jobs:
            if job.get("id") != job_id:
                continue
            if job.get("status") in STOPPED and status not in STOPPED:
                return
            final = status or ("error" if error else "done")
            job["status"] = final
            job["phase"] = final
            job["finished_at"] = _now()
            job["heartbeat_at"] = _now()
            if final == "cancelled":
                job["detail"] = "Đã hủy"
                job.pop("error", None)
            elif final == "interrupted":
                job["detail"] = job.get("detail") or "Bị ngắt"
            elif error:
                job["error"] = error
                job["detail"] = (error or "")[:180]
                job.pop("result", None)
            else:
                job.pop("error", None)
                job["detail"] = "Xong"
                if result is not None:
                    job["result"] = result
            break
        store["jobs"] = jobs
        _write_store(store)


def requeue_job(job_id: str, *, delay_sec: float, error: str) -> bool:
    """Put a job back in the queue after a transient provider failure."""
    requeued = False
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        for job in jobs:
            if job.get("id") != job_id:
                continue
            if job.get("status") in STOPPED:
                return False
            job["status"] = "queued"
            job["phase"] = "retry"
            job["detail"] = f"Lỗi tạm thời — thử lại sau {int(delay_sec)}s"
            job["error"] = (error or "")[:180]
            job["not_before"] = _now_plus(delay_sec)
            job["heartbeat_at"] = _now()
            job.pop("finished_at", None)
            requeued = True
            break
        if requeued:
            store["jobs"] = jobs
            _write_store(store)
    if requeued:
        _wake.set()
    return requeued


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


def _fail_job(job: dict[str, Any], error: str) -> None:
    complete_job(job["id"], error=error)
    job["status"] = "error"
    job["error"] = error
    # Annotate uses Gemini; a 429/timeout should not block DeepSeek QA on an existing draft.
    if job.get("kind") == "annotate":
        _enqueue_followups(job)


def _retry_job(job: dict[str, Any], error: str) -> bool:
    from ..settings import job_guard_limits

    if not is_transient_error(error):
        return False
    max_attempts, _timeout = job_guard_limits()
    attempts = int(job.get("attempts") or 0)
    if attempts >= max_attempts:
        return False
    delay = retry_delay_for(attempts)
    if not requeue_job(job["id"], delay_sec=delay, error=error):
        return False
    job_log_event(
        "retry_job",
        job_id=job["id"],
        work_id=job.get("work_id"),
        chapter=job.get("chapter"),
        kind=job.get("kind"),
        attempt=attempts,
        of=max_attempts,
        delay=int(delay),
        error=error[:140],
    )
    return True


def process_next_job() -> dict[str, Any] | None:
    job = claim_next()
    if not job:
        return None
    token = _current_job_id.set(str(job["id"]))
    try:
        raise_if_stopped()
        result = execute_job(job)
        raise_if_stopped()
        complete_job(job["id"], result=result)
        job["status"] = "done"
        job["phase"] = "done"
        job["result"] = result
        job_log_event(
            "done",
            job_id=job["id"],
            work_id=job.get("work_id"),
            chapter=job.get("chapter"),
            kind=job.get("kind"),
            thread=threading.current_thread().name,
        )
        _enqueue_followups(job)
    except JobCancelled:
        complete_job(job["id"], status="cancelled")
        job["status"] = "cancelled"
        job["phase"] = "cancelled"
        job["detail"] = "Đã hủy"
        job_log_event(
            "cancelled",
            job_id=job["id"],
            work_id=job.get("work_id"),
            chapter=job.get("chapter"),
            kind=job.get("kind"),
        )
    except JobGuardError as exc:
        job_log_event(
            "guard",
            job_id=job["id"],
            work_id=job.get("work_id"),
            chapter=job.get("chapter"),
            kind=job.get("kind"),
            error=str(exc)[:180],
        )
        _fail_job(job, str(exc))
    except Exception as exc:
        if job["id"] in _cancel_flags:
            complete_job(job["id"], status="cancelled")
            job["status"] = "cancelled"
            job_log_event(
                "cancelled",
                job_id=job["id"],
                work_id=job.get("work_id"),
                chapter=job.get("chapter"),
                kind=job.get("kind"),
                error=str(exc)[:180],
            )
        elif _retry_job(job, str(exc)):
            job["status"] = "queued"
        else:
            job_log_event(
                "error",
                job_id=job["id"],
                work_id=job.get("work_id"),
                chapter=job.get("chapter"),
                kind=job.get("kind"),
                error=str(exc)[:180],
                thread=threading.current_thread().name,
            )
            _fail_job(job, str(exc))
    finally:
        _current_job_id.reset(token)
    return job


def worker_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        job = process_next_job()
        if job is not None:
            continue
        if _idle_thread_should_exit():
            return
        _wake.wait(timeout=0.75)
        _wake.clear()


def _idle_thread_should_exit() -> bool:
    from ..settings import worker_limits

    current = threading.current_thread()
    with _pool_lock:
        min_workers, max_workers = worker_limits()
        queued, running = _queue_depth()
        desired = desired_worker_count(queued, running, min_workers, max_workers)
        alive = [thread for thread in _threads if thread.is_alive()]
        if len(alive) <= desired:
            return False
        _threads[:] = [thread for thread in alive if thread is not current]
        job_log_event(
            "worker_exit",
            name=current.name,
            desired=desired,
            alive=len(_threads),
            queued=queued,
            running=running,
        )
        return True


def _scale_workers_locked() -> None:
    global _stop, _next_worker
    from ..settings import worker_limits

    if _stop is None or _stop.is_set():
        _stop = threading.Event()
    min_workers, max_workers = worker_limits()
    queued, running = _queue_depth()
    desired = desired_worker_count(queued, running, min_workers, max_workers)
    _threads[:] = [thread for thread in _threads if thread.is_alive()]
    while len(_threads) < desired:
        _next_worker += 1
        thread = threading.Thread(
            target=worker_loop,
            args=(_stop,),
            name=f"kh-translate-worker-{_next_worker}",
            daemon=True,
        )
        _threads.append(thread)
        thread.start()
        job_log_event(
            "worker_start",
            name=thread.name,
            desired=desired,
            alive=len(_threads),
            queued=queued,
            running=running,
            min_workers=min_workers,
            max_workers=max_workers,
        )
    if desired:
        _wake.set()


def scale_workers() -> None:
    if not worker_enabled():
        return
    with _pool_lock:
        _scale_workers_locked()


def start_worker() -> None:
    global _requeued
    if not worker_enabled():
        return
    with _pool_lock:
        first = not _requeued
        _requeued = True
    if first:
        n = interrupt_stale_running()
        job_log_event("worker_boot", interrupted=n, enabled=True)
    scale_workers()


def stop_worker() -> None:
    global _stop, _threads, _requeued
    if _stop is not None:
        _stop.set()
        _wake.set()
    threads = list(_threads)
    for thread in threads:
        if thread.is_alive():
            thread.join(timeout=2.0)
    job_log_event("worker_stop", alive=sum(1 for thread in threads if thread.is_alive()))
    _threads = []
    _stop = None
    _requeued = False
