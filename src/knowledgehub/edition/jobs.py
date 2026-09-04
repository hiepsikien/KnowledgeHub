"""File-backed read-edition job queue with a scalable background worker pool."""

from __future__ import annotations

import json
import logging
import secrets
import threading
from collections import deque
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..jsonfile import quarantine_corrupt, write_json_atomic
from ..paths import corpus_root
from ..translation.jobs import (
    HARD_JOB_LIMIT_SEC,
    JobCancelled,
    JobGuardError,
    desired_worker_count,
    is_transient_error,
    retry_delay_for,
    worker_enabled,
)

KIND_ORDER = ("macro", "parse", "qa", "hitl_scan")
KINDS = KIND_ORDER
KIND_RANK = {kind: index for index, kind in enumerate(KIND_ORDER)}
WORK_SCOPE = "*"
ACTIVE = frozenset({"queued", "running"})
STOPPED = frozenset({"cancelled", "interrupted"})
HITL_KINDS = frozenset({"wrap", "footnotes", "quotes"})

_lock = threading.Lock()
_pool_lock = threading.Lock()
_wake = threading.Event()
_stop: threading.Event | None = None
_threads: list[threading.Thread] = []
_next_worker = 0
_requeued = False
_cancel_flags: set[str] = set()
_current_job_id: ContextVar[str | None] = ContextVar("kh_edition_job_id", default=None)
_events: deque[dict[str, Any]] = deque(maxlen=80)
log = logging.getLogger("knowledgehub.edition.jobs")


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


def current_job_id() -> str | None:
    return _current_job_id.get()


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


def jobs_path() -> Path:
    return corpus_root() / ".edition-jobs.json"


def worker_alive() -> bool:
    return worker_status()["alive"] > 0


def worker_status() -> dict[str, int]:
    from ..settings import edition_worker_limits

    min_workers, max_workers = edition_worker_limits()
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
        "edition job store unreadable (%s); queue reset. Saved copy: %s",
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
        log.error("cannot read edition job store: %s", exc)
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
        "params",
    )
    payload = {key: job.get(key) for key in keys if job.get(key) is not None}
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    for key in ("hitl_kind", "scope", "use_llm", "force", "keep_toc"):
        if key in params and key not in payload:
            payload[key] = params[key]
    return payload


def list_jobs(work_id: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        jobs = list(_read_store().get("jobs") or [])
    if work_id:
        jobs = [job for job in jobs if job.get("work_id") == work_id]
    return [_public(job) for job in reversed(jobs)]


def jobs_payload(work_id: str | None = None) -> dict[str, Any]:
    return {
        "jobs": list_jobs(work_id),
        "log": recent_job_log(),
        "worker_alive": worker_alive(),
        "workers": worker_status(),
    }


def _params_of(job: dict[str, Any]) -> dict[str, Any]:
    params = job.get("params")
    return dict(params) if isinstance(params, dict) else {}


def _is_work_scoped(job: dict[str, Any]) -> bool:
    if job.get("kind") == "macro":
        return True
    if job.get("kind") == "hitl_scan" and _params_of(job).get("scope") == "book":
        return True
    return str(job.get("chapter") or "") in {"", WORK_SCOPE}


def _identity(job: dict[str, Any]) -> tuple[Any, ...]:
    kind = str(job.get("kind") or "")
    params = _params_of(job)
    if kind == "macro":
        return ("macro",)
    if kind == "hitl_scan":
        return (
            "hitl_scan",
            params.get("hitl_kind"),
            params.get("scope") or "chapter",
            job.get("chapter") or params.get("chapter_id") or WORK_SCOPE,
        )
    return (kind, job.get("chapter"))


def _find_active(jobs: list[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any] | None:
    ident = _identity(candidate)
    work_id = candidate.get("work_id")
    for job in jobs:
        if job.get("status") not in ACTIVE:
            continue
        if job.get("work_id") != work_id:
            continue
        if _identity(job) == ident:
            return job
    return None


def _claim_blocked(job: dict[str, Any], running: list[dict[str, Any]]) -> bool:
    work_id = job.get("work_id")
    on_work = [row for row in running if row.get("work_id") == work_id]
    if not on_work:
        return False
    if _is_work_scoped(job) or any(_is_work_scoped(row) for row in on_work):
        return True
    chapter = str(job.get("chapter") or "")
    if chapter and chapter != WORK_SCOPE:
        if any(str(row.get("chapter") or "") == chapter for row in on_work):
            return True
    if job.get("kind") == "hitl_scan":
        hitl_kind = _params_of(job).get("hitl_kind")
        if any(
            row.get("kind") == "hitl_scan" and _params_of(row).get("hitl_kind") == hitl_kind
            for row in on_work
        ):
            return True
    return False


def _validate_work(work_id: str) -> str:
    from ..catalog import get_work

    text = (work_id or "").strip()
    if not text:
        raise ValueError("work_id required")
    get_work(text)
    return text


def _validate_enqueue(work_id: str, kind: str, chapter: str, params: dict[str, Any]) -> None:
    from .read_edition import package_dir_for_work
    from .read_edition_steps import ReadEditionStepError, ensure_ready_to_parse, load_hitl_job, load_structure

    if kind == "macro":
        if not params.get("keep_toc"):
            return
        try:
            package_dir, _meta, _work = package_dir_for_work(work_id)
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        structure = load_structure(package_dir)
        if not structure:
            raise ValueError("Run phân đoạn first, then confirm TOC")
        toc = dict((structure.get("hitl") or {}).get("toc") or {})
        if toc.get("status") not in {"yes", "no", "none"}:
            raise ValueError("Confirm TOC before phân loại lại")
        return
    try:
        package_dir, _meta, _work = package_dir_for_work(work_id)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    structure = load_structure(package_dir)
    if not structure:
        raise ValueError("Run macro step first (structure.json missing)")
    sections = {str(row.get("section_id")) for row in (structure.get("sections") or [])}
    if kind in {"parse", "qa"}:
        if chapter == WORK_SCOPE or not chapter:
            raise ValueError("chapter_id required")
        if chapter not in sections:
            raise ValueError(f"Unknown section: {chapter}")
        if kind == "parse":
            try:
                ensure_ready_to_parse(work_id)
            except ReadEditionStepError as exc:
                raise ValueError(str(exc)) from exc
        if kind == "qa":
            path = package_dir / "chapters" / f"{chapter}.json"
            if not path.is_file():
                raise ValueError(f"{chapter} not parsed — run micro parse first")
        return
    hitl_kind = str(params.get("hitl_kind") or "")
    if hitl_kind not in HITL_KINDS:
        raise ValueError(f"unknown HITL kind: {hitl_kind}")
    scope = str(params.get("scope") or "chapter")
    if scope not in {"chapter", "book"}:
        raise ValueError("scope must be chapter or book")
    if scope == "chapter":
        if chapter == WORK_SCOPE or not chapter:
            raise ValueError("chapter_id required for trial scan")
        if chapter not in sections:
            raise ValueError(f"Unknown section: {chapter}")
    else:
        existing = load_hitl_job(package_dir, hitl_kind)
        if not existing.get("trial_confirmed"):
            raise ValueError("Xác nhận chương thử trước khi chạy toàn văn bản")


def enqueue_job(
    work_id: str,
    kind: str,
    *,
    chapter: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"Unknown job kind: {kind!r}")
    source_work_id = _validate_work(work_id)
    payload_params = dict(params or {})
    if kind == "hitl_scan":
        payload_params["hitl_kind"] = str(payload_params.get("hitl_kind") or "")
        payload_params["scope"] = str(payload_params.get("scope") or "chapter")
    ch = WORK_SCOPE if kind == "macro" or payload_params.get("scope") == "book" else str(chapter or "").strip()
    if kind == "hitl_scan" and payload_params.get("scope") == "chapter":
        payload_params["chapter_id"] = ch
    _validate_enqueue(source_work_id, kind, ch, payload_params)
    candidate = {
        "work_id": source_work_id,
        "chapter": ch or WORK_SCOPE,
        "kind": kind,
        "params": payload_params,
    }
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        existing = _find_active(jobs, candidate)
        if existing:
            payload = _public(existing)
            payload["created"] = False
            job_log_event(
                "enqueue_duplicate",
                job_id=existing.get("id"),
                work_id=source_work_id,
                chapter=existing.get("chapter"),
                kind=kind,
                status=existing.get("status"),
            )
            return payload
        detail = {
            "macro": "Đã xếp hàng phân đoạn",
            "parse": f"Đã xếp hàng parse {ch}",
            "qa": f"Đã xếp hàng QA {ch}",
            "hitl_scan": "Đã xếp hàng quét HITL",
        }.get(kind, "Đã xếp hàng")
        job = {
            "id": secrets.token_hex(8),
            "work_id": source_work_id,
            "chapter": candidate["chapter"],
            "kind": kind,
            "params": payload_params,
            "status": "queued",
            "phase": "queued",
            "detail": detail,
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
        work_id=source_work_id,
        chapter=job["chapter"],
        kind=kind,
        created=True,
        queued=_queue_depth()[0],
        running=_queue_depth()[1],
        workers=worker_status()["alive"],
    )
    return payload


def enqueue_parse_chapters(
    work_id: str,
    chapter_ids: list[str],
    *,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    ids = [str(ch).strip() for ch in chapter_ids if str(ch).strip()]
    if not ids:
        raise ValueError("chapter_ids required")
    source_work_id = _validate_work(work_id)
    params: dict[str, Any] = {}
    if use_llm is not None:
        params["use_llm"] = use_llm
    for chapter in ids:
        _validate_enqueue(source_work_id, "parse", chapter, params)
    jobs: list[dict[str, Any]] = []
    for chapter in ids:
        jobs.append(enqueue_job(source_work_id, "parse", chapter=chapter, params=params or None))
    created = sum(1 for job in jobs if job.get("created"))
    job_log_event(
        "enqueue_parse_batch",
        work_id=work_id,
        enqueued=created,
        total=len(jobs),
        queued=_queue_depth()[0],
        running=_queue_depth()[1],
        workers=worker_status()["alive"],
    )
    snap = jobs_payload(work_id)
    return {
        "work_id": work_id,
        "kind": "parse",
        "enqueued": created,
        "jobs": jobs,
        "chapter_ids": ids,
        "log": snap["log"],
        "worker_alive": snap["worker_alive"],
        "workers": snap["workers"],
    }


def enqueue_edition_job(
    work_id: str,
    *,
    kind: str,
    chapter_id: str | None = None,
    chapter_ids: list[str] | None = None,
    hitl_kind: str | None = None,
    scope: str | None = None,
    use_llm: bool | None = None,
    force: bool = False,
    keep_toc: bool = False,
) -> dict[str, Any]:
    if kind == "parse" and chapter_ids:
        return enqueue_parse_chapters(work_id, chapter_ids, use_llm=use_llm)
    params: dict[str, Any] = {}
    if kind == "macro":
        params["force"] = bool(force)
        params["keep_toc"] = bool(keep_toc)
        if use_llm is not None:
            params["use_llm"] = use_llm
    elif kind == "parse":
        if not chapter_id:
            raise ValueError("Provide chapter_id or chapter_ids")
        if use_llm is not None:
            params["use_llm"] = use_llm
    elif kind == "qa":
        if not chapter_id:
            raise ValueError("chapter_id required")
        if use_llm is not None:
            params["use_llm"] = use_llm
    elif kind == "hitl_scan":
        params["hitl_kind"] = hitl_kind
        params["scope"] = scope or "chapter"
        if params["scope"] == "chapter" and not chapter_id:
            raise ValueError("chapter_id required for trial scan")
    else:
        raise ValueError(f"Unknown job kind: {kind!r}")
    job = enqueue_job(work_id, kind, chapter=chapter_id, params=params or None)
    payload = jobs_payload(work_id)
    payload["job"] = job
    payload["enqueued"] = 1 if job.get("created") else 0
    payload["jobs"] = list_jobs(work_id)
    return payload


def interrupt_stale_running(*, include_queued: bool = False) -> int:
    stale = {"running"}
    if include_queued:
        stale.add("queued")
    n = 0
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        for job in jobs:
            if job.get("status") not in stale:
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
            job_log_event("interrupt_stale", count=n, include_queued=include_queued)
    return n


def cancel_jobs(
    *,
    work_id: str | None = None,
    chapter: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
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
            if chapter and str(job.get("chapter") or "") != chapter:
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
            chapter=chapter,
            job_id=job_id,
            ids=",".join(str(job.get("id") or "") for job in cancelled),
        )
    result = jobs_payload(work_id)
    result["cancelled"] = len(cancelled)
    result["cancelled_jobs"] = cancelled
    return result


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
    from ..settings import edition_job_guard_limits

    _, timeout_sec = edition_job_guard_limits()
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
    from ..settings import edition_job_guard_limits

    max_attempts, _timeout = edition_job_guard_limits()
    with _lock:
        store = _read_store()
        jobs = list(store.get("jobs") or [])
        running = [job for job in jobs if job.get("status") == "running"]
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
            if int(job.get("attempts") or 0) >= max_attempts:
                job["status"] = "error"
                job["phase"] = "error"
                job["detail"] = f"Quá số lần thử ({max_attempts})"
                job["error"] = f"max_attempts {max_attempts}"
                job["finished_at"] = _now()
                job["heartbeat_at"] = _now()
                dirty = True
                continue
            if _claim_blocked(job, running):
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


def _result_summary(kind: str, result: dict[str, Any]) -> dict[str, Any]:
    if kind == "macro":
        manifest = result.get("manifest") if isinstance(result.get("manifest"), dict) else {}
        return {
            "built": result.get("built"),
            "package_dir": result.get("package_dir"),
            "chapter_count": manifest.get("chapter_count")
            or len(manifest.get("chapters") or []),
        }
    if kind == "parse":
        return {
            "chapter_id": result.get("chapter_id"),
            "block_count": result.get("block_count"),
            "micro_status": result.get("micro_status"),
        }
    if kind == "qa":
        return {
            "chapter_id": result.get("chapter_id"),
            "passed": result.get("passed"),
            "summary_vi": str(result.get("summary_vi") or "")[:180] or None,
        }
    if kind == "hitl_scan":
        return {
            "kind": result.get("kind"),
            "scope": result.get("scope"),
            "summary": result.get("summary") or {},
            "trial_chapter_id": result.get("trial_chapter_id"),
            "status": result.get("status"),
        }
    return {}


def execute_job(job: dict[str, Any]) -> dict[str, Any]:
    from ..read_edition_service import parse_micro, run_macro, run_qa, scan_hitl

    kind = str(job.get("kind") or "")
    work_id = str(job.get("work_id") or "")
    chapter = str(job.get("chapter") or "")
    params = _params_of(job)
    if kind == "macro":
        report_progress("macro", "Đang phân đoạn…")
        return run_macro(
            work_id,
            force=bool(params.get("force")),
            use_llm=bool(params["use_llm"]) if "use_llm" in params else True,
            keep_toc=bool(params.get("keep_toc")),
        )
    if kind == "parse":
        report_progress("parse", f"Đang parse REF {chapter}…")
        return parse_micro(
            work_id,
            chapter,
            use_llm=params.get("use_llm"),
        )
    if kind == "qa":
        report_progress("qa", f"Đang QA {chapter}…")
        return run_qa(
            work_id,
            chapter_id=chapter,
            use_llm=bool(params["use_llm"]) if "use_llm" in params else True,
        )
    if kind == "hitl_scan":
        scope = str(params.get("scope") or "chapter")
        hitl_kind = str(params.get("hitl_kind") or "")
        report_progress("scan", f"Đang quét {hitl_kind}…")
        return scan_hitl(
            work_id,
            hitl_kind,
            chapter_id=None if scope == "book" else chapter,
            scope=scope,
        )
    raise ValueError(f"Unknown job kind: {kind!r}")


def _fail_job(job: dict[str, Any], error: str) -> None:
    complete_job(job["id"], error=error)
    job["status"] = "error"
    job["error"] = error


def _retry_job(job: dict[str, Any], error: str) -> bool:
    from ..settings import edition_job_guard_limits

    if not is_transient_error(error):
        return False
    max_attempts, _timeout = edition_job_guard_limits()
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
        summary = _result_summary(str(job.get("kind") or ""), result if isinstance(result, dict) else {})
        complete_job(job["id"], result=summary or None)
        job["status"] = "done"
        job["phase"] = "done"
        job["result"] = summary
        job_log_event(
            "done",
            job_id=job["id"],
            work_id=job.get("work_id"),
            chapter=job.get("chapter"),
            kind=job.get("kind"),
            thread=threading.current_thread().name,
        )
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
    from ..settings import edition_worker_limits

    current = threading.current_thread()
    with _pool_lock:
        min_workers, max_workers = edition_worker_limits()
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
    from ..settings import edition_worker_limits

    if _stop is None or _stop.is_set():
        _stop = threading.Event()
    min_workers, max_workers = edition_worker_limits()
    queued, running = _queue_depth()
    desired = desired_worker_count(queued, running, min_workers, max_workers)
    _threads[:] = [thread for thread in _threads if thread.is_alive()]
    while len(_threads) < desired:
        _next_worker += 1
        thread = threading.Thread(
            target=worker_loop,
            args=(_stop,),
            name=f"kh-edition-worker-{_next_worker}",
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
        n = interrupt_stale_running(include_queued=True)
        job_log_event("worker_boot", interrupted=n, enabled=True, include_queued=True)
    scale_workers()


def stop_worker() -> None:
    global _stop, _threads, _requeued
    dropped = interrupt_stale_running(include_queued=True)
    if _stop is not None:
        _stop.set()
        _wake.set()
    threads = list(_threads)
    for thread in threads:
        if thread.is_alive():
            thread.join(timeout=2.0)
    dropped += interrupt_stale_running(include_queued=True)
    job_log_event(
        "worker_stop",
        alive=sum(1 for thread in threads if thread.is_alive()),
        interrupted=dropped,
    )
    _threads = []
    _stop = None
    _requeued = False
