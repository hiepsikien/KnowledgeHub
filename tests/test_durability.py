from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowledgehub.jsonfile import quarantine_corrupt, write_json_atomic
from knowledgehub.server import create_app
from knowledgehub.settings import save_settings
from knowledgehub.translation.jobs import (
    HARD_JOB_LIMIT_SEC,
    JobCancelled,
    JobGuardError,
    _current_job_id,
    enqueue_job,
    jobs_path,
    raise_if_stopped,
    update_job_progress,
)
from knowledgehub.translation.project import init_translation_project, select_translation_mode

WORK_ID = "grotius--freedom_of_the_seas"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sources = tmp_path / "sources/grotius/raw"
    sources.mkdir(parents=True)
    (sources / "freedom_of_the_seas.txt").write_text(
        "CHAPTER I\n\nEnglish paragraph one.\n\nCHAPTER II\n\nEnglish paragraph two.\n",
        encoding="utf-8",
    )
    (catalog / "works.json").write_text(
        json.dumps(
            [
                {
                    "id": WORK_ID,
                    "title": "The Freedom of the Seas",
                    "author_id": "grotius",
                    "language": "en",
                    "content_file": "sources/grotius/raw/freedom_of_the_seas.txt",
                }
            ]
        ),
        encoding="utf-8",
    )
    (catalog / "authors.json").write_text(
        json.dumps([{"id": "grotius", "name": "Grotius"}]), encoding="utf-8"
    )
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(tmp_path))
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    init_translation_project(WORK_ID)
    sample = tmp_path / f"translations/{WORK_ID}/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode(WORK_ID, "tight")
    return TestClient(create_app())


def test_write_json_atomic_replaces_whole_file(tmp_path: Path):
    target = tmp_path / "nested" / "data.json"
    write_json_atomic(target, {"a": 1})
    write_json_atomic(target, {"a": 2, "b": [1, 2, 3]})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2, "b": [1, 2, 3]}
    assert list(target.parent.iterdir()) == [target]
    assert target.stat().st_mode & 0o777 == 0o644


def test_write_json_atomic_leaves_old_file_when_serialising_fails(tmp_path: Path):
    target = tmp_path / "data.json"
    write_json_atomic(target, {"keep": "me"})
    with pytest.raises(TypeError):
        write_json_atomic(target, {"bad": object()})
    assert json.loads(target.read_text(encoding="utf-8")) == {"keep": "me"}
    assert list(target.parent.iterdir()) == [target]


def test_concurrent_atomic_writes_never_produce_a_partial_file(tmp_path: Path):
    target = tmp_path / "data.json"
    write_json_atomic(target, {"jobs": []})
    stop = threading.Event()
    corrupt: list[str] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                corrupt.append(str(exc))
                return

    def writer(index: int) -> None:
        for step in range(40):
            write_json_atomic(target, {"jobs": [{"id": f"{index}-{step}"} for _ in range(60)]})

    watcher = threading.Thread(target=reader)
    watcher.start()
    writers = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for thread in writers:
        thread.start()
    for thread in writers:
        thread.join()
    stop.set()
    watcher.join()
    assert corrupt == []


def test_quarantine_corrupt_moves_file_aside(tmp_path: Path):
    target = tmp_path / "broken.json"
    target.write_text('{"jobs": [', encoding="utf-8")
    moved = quarantine_corrupt(target)
    assert moved is not None
    assert not target.exists()
    assert moved.read_text(encoding="utf-8") == '{"jobs": ['
    assert quarantine_corrupt(tmp_path / "absent.json") is None


def test_corrupt_job_store_is_kept_for_inspection(client: TestClient, tmp_path: Path):
    enqueue_job(WORK_ID, "II", "draft")
    path = jobs_path()
    path.write_text('{"jobs": [{"id": "half', encoding="utf-8")
    res = client.get(f"/api/translations/{WORK_ID}/jobs")
    assert res.status_code == 200
    assert res.json()["jobs"] == []
    backups = list(tmp_path.glob(".translation-jobs.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"jobs": [{"id": "half'
    assert any(row["event"] == "store_corrupt" for row in res.json()["log"])


def _stamp(seconds_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).replace(microsecond=0).isoformat()


def _run_job_with_clock(job_id: str, *, started_ago: float, heartbeat_ago: float) -> None:
    path = jobs_path()
    store = json.loads(path.read_text(encoding="utf-8"))
    for row in store["jobs"]:
        if row["id"] == job_id:
            row["status"] = "running"
            row["started_at"] = _stamp(started_ago)
            row["heartbeat_at"] = _stamp(heartbeat_ago)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_guard_lets_a_long_job_run_while_it_reports_progress(client: TestClient):
    save_settings({"translation": {"job_timeout_sec": 60}})
    job = enqueue_job(WORK_ID, "II", "draft")
    _run_job_with_clock(job["id"], started_ago=3000, heartbeat_ago=5)
    token = _current_job_id.set(job["id"])
    try:
        raise_if_stopped()
    finally:
        _current_job_id.reset(token)


def test_guard_kills_a_job_that_stopped_reporting_progress(client: TestClient):
    save_settings({"translation": {"job_timeout_sec": 60}})
    job = enqueue_job(WORK_ID, "II", "draft")
    _run_job_with_clock(job["id"], started_ago=3000, heartbeat_ago=200)
    token = _current_job_id.set(job["id"])
    try:
        with pytest.raises(JobGuardError, match="no progress for 200s"):
            raise_if_stopped()
    finally:
        _current_job_id.reset(token)


def test_guard_enforces_a_hard_ceiling_even_with_a_live_heartbeat(client: TestClient):
    save_settings({"translation": {"job_timeout_sec": 600}})
    job = enqueue_job(WORK_ID, "II", "draft")
    _run_job_with_clock(job["id"], started_ago=HARD_JOB_LIMIT_SEC + 60, heartbeat_ago=1)
    token = _current_job_id.set(job["id"])
    try:
        with pytest.raises(JobGuardError, match="hard limit"):
            raise_if_stopped()
    finally:
        _current_job_id.reset(token)


def test_progress_report_resets_the_stall_clock(client: TestClient):
    save_settings({"translation": {"job_timeout_sec": 60}})
    job = enqueue_job(WORK_ID, "II", "draft")
    _run_job_with_clock(job["id"], started_ago=3000, heartbeat_ago=200)
    token = _current_job_id.set(job["id"])
    try:
        update_job_progress(job["id"], phase="drafting", detail="Đang nháp phần 4/6…")
        raise_if_stopped()
    finally:
        _current_job_id.reset(token)


def test_guard_stops_a_cancelled_job_before_the_timeout(client: TestClient):
    from knowledgehub.translation.jobs import cancel_jobs

    job = enqueue_job(WORK_ID, "II", "draft")
    token = _current_job_id.set(job["id"])
    try:
        cancel_jobs(job_id=job["id"])
        with pytest.raises(JobCancelled):
            raise_if_stopped()
    finally:
        _current_job_id.reset(token)
