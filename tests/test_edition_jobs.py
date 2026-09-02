from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from knowledgehub.server import create_app
from knowledgehub.settings import save_settings

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
    works = [
        {
            "id": WORK_ID,
            "title": "The Freedom of the Seas",
            "author_id": "grotius",
            "language": "en",
            "content_file": "sources/grotius/raw/freedom_of_the_seas.txt",
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(json.dumps([{"id": "grotius", "name": "Grotius"}]), encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(tmp_path))
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    monkeypatch.setenv("KNOWLEDGEHUB_REF_LLM_DEFAULT", "0")
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    from knowledgehub.hash import refresh_hashes

    refresh_hashes()
    yield TestClient(create_app())
    from knowledgehub.edition.jobs import stop_worker as stop_edition_worker
    from knowledgehub.translation.jobs import stop_worker

    stop_edition_worker()
    stop_worker()


def _ready_to_parse(client: TestClient) -> list[str]:
    macro = client.post(f"/api/works/{WORK_ID}/read-edition/macro", json={"use_llm": False})
    assert macro.status_code == 200, macro.text
    toc = client.post(f"/api/works/{WORK_ID}/read-edition/toc", json={"status": "none"})
    assert toc.status_code == 200, toc.text
    review = client.get(f"/api/works/{WORK_ID}/read-edition/review")
    assert review.status_code == 200, review.text
    for sid in review.json()["health"].get("untreated_flags") or []:
        confirmed = client.post(
            f"/api/works/{WORK_ID}/read-edition/structure/edit",
            json={"action": "confirm", "section_id": sid},
        )
        assert confirmed.status_code == 200, confirmed.text
    layout = client.post(f"/api/works/{WORK_ID}/read-edition/layout")
    assert layout.status_code == 200, layout.text
    chapters = layout.json()["manifest"]["chapters"]
    return [row["chapter_id"] for row in chapters]


def test_settings_saves_edition_workers(client: TestClient, tmp_path: Path):
    res = client.post(
        "/api/settings",
        json={"edition": {"min_workers": 2, "max_workers": 6, "max_attempts": 4, "job_timeout_sec": 900}},
    )
    assert res.status_code == 200, res.text
    ed = res.json()["settings"]["edition"]
    assert (ed["min_workers"], ed["max_workers"]) == (2, 6)
    assert (ed["max_attempts"], ed["job_timeout_sec"]) == (4, 900)
    assert ed["use_llm_macro"] is True
    stored = json.loads((tmp_path / "hub-settings.json").read_text(encoding="utf-8"))
    assert stored["edition"]["max_workers"] == 6
    again = client.post("/api/settings", json={"edition": {"use_llm_qa": False}})
    kept = again.json()["settings"]["edition"]
    assert kept["min_workers"] == 2
    assert kept["max_workers"] == 6
    assert kept["use_llm_qa"] is False


def test_settings_clamps_edition_workers(client: TestClient):
    res = client.post("/api/settings", json={"edition": {"min_workers": 5, "max_workers": 2}})
    ed = res.json()["settings"]["edition"]
    assert ed["min_workers"] == 2
    assert ed["max_workers"] == 2
    high = client.post("/api/settings", json={"edition": {"min_workers": -3, "max_workers": 99}})
    ed = high.json()["settings"]["edition"]
    assert ed["min_workers"] == 0
    assert ed["max_workers"] == 8


def test_enqueue_macro_job_and_dedupe(client: TestClient):
    first = client.post(
        f"/api/works/{WORK_ID}/read-edition/jobs",
        json={"kind": "macro", "use_llm": False},
    )
    assert first.status_code == 200, first.text
    job = first.json()["job"]
    assert job["status"] == "queued"
    assert job["kind"] == "macro"
    assert job["created"] is True
    second = client.post(
        f"/api/works/{WORK_ID}/read-edition/jobs",
        json={"kind": "macro", "use_llm": False},
    )
    assert second.status_code == 200
    assert second.json()["job"]["id"] == job["id"]
    assert second.json()["job"]["created"] is False
    listed = client.get(f"/api/works/{WORK_ID}/read-edition/jobs").json()
    assert listed["worker_alive"] is False
    assert listed["workers"]["min_workers"] == 1
    assert listed["workers"]["max_workers"] == 2
    assert any(row["id"] == job["id"] for row in listed["jobs"])
    status = client.get(f"/api/works/{WORK_ID}/read-edition").json()
    assert any(row["id"] == job["id"] for row in status["jobs"])
    assert "workers" in status


def test_process_next_job_runs_macro(client: TestClient, tmp_path: Path):
    from knowledgehub.edition.jobs import enqueue_job, process_next_job

    enqueue_job(WORK_ID, "macro", params={"use_llm": False})
    with patch("knowledgehub.read_edition_service.run_macro") as mock_macro:
        mock_macro.return_value = {
            "built": True,
            "package_dir": "read-editions/x",
            "manifest": {"chapter_count": 2},
        }
        done = process_next_job()
    assert done["status"] == "done"
    mock_macro.assert_called_once_with(WORK_ID, force=False, use_llm=False, keep_toc=False)
    store = json.loads((tmp_path / ".edition-jobs.json").read_text(encoding="utf-8"))
    job = next(row for row in store["jobs"] if row["kind"] == "macro")
    assert job["status"] == "done"
    assert job["result"]["chapter_count"] == 2


def test_claim_next_macro_blocks_parse(client: TestClient):
    from knowledgehub.edition.jobs import claim_next, complete_job, enqueue_job

    ids = _ready_to_parse(client)
    macro = enqueue_job(WORK_ID, "macro", params={"use_llm": False, "force": True})
    enqueue_job(WORK_ID, "parse", chapter=ids[0], params={"use_llm": False})
    claimed = claim_next()
    assert claimed["id"] == macro["id"]
    assert claim_next() is None
    complete_job(claimed["id"], result={"ok": True})
    waiting = claim_next()
    assert waiting["kind"] == "parse"
    assert waiting["chapter"] == ids[0]


def test_claim_next_parses_chapters_in_parallel(client: TestClient):
    from knowledgehub.edition.jobs import claim_next, enqueue_job

    ids = _ready_to_parse(client)
    assert len(ids) >= 2
    first = enqueue_job(WORK_ID, "parse", chapter=ids[0], params={"use_llm": False})
    enqueue_job(WORK_ID, "parse", chapter=ids[1], params={"use_llm": False})
    claimed = claim_next()
    assert claimed["id"] == first["id"]
    other = claim_next()
    assert other["chapter"] == ids[1]
    assert claim_next() is None


def test_enqueue_parse_batch(client: TestClient):
    ids = _ready_to_parse(client)
    res = client.post(
        f"/api/works/{WORK_ID}/read-edition/jobs",
        json={"kind": "parse", "chapter_ids": ids, "use_llm": False},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["enqueued"] == len(ids)
    assert {job["chapter"] for job in body["jobs"]} == set(ids)
    assert all(job["kind"] == "parse" for job in body["jobs"])


def test_cancel_jobs_api(client: TestClient):
    first = client.post(
        f"/api/works/{WORK_ID}/read-edition/jobs",
        json={"kind": "macro", "use_llm": False},
    )
    assert first.status_code == 200, first.text
    cancelled = client.post(f"/api/works/{WORK_ID}/read-edition/jobs/cancel", json={})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["cancelled"] >= 1
    listed = client.get(f"/api/works/{WORK_ID}/read-edition/jobs").json()
    assert not any(job["status"] in {"queued", "running"} for job in listed["jobs"])


def test_sync_macro_endpoint_still_runs(client: TestClient):
    macro = client.post(f"/api/works/{WORK_ID}/read-edition/macro", json={"use_llm": False})
    assert macro.status_code == 200, macro.text
    assert macro.json()["built"] is True


def test_two_edition_workers_run_parses_in_parallel(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from knowledgehub.edition.jobs import enqueue_job, list_jobs, start_worker, stop_worker, worker_status

    ids = _ready_to_parse(client)
    assert len(ids) >= 2
    save_settings({"edition": {"min_workers": 1, "max_workers": 2}})
    lock = threading.Lock()
    current = 0
    peak = 0
    barrier = threading.Barrier(2)

    def fake_execute(job):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        try:
            barrier.wait(timeout=5)
            time.sleep(0.05)
            return {"chapter_id": job.get("chapter"), "block_count": 1, "micro_status": "complete"}
        finally:
            with lock:
                current -= 1

    monkeypatch.setattr("knowledgehub.edition.jobs.execute_job", fake_execute)
    for chapter in ids[:2]:
        enqueue_job(WORK_ID, "parse", chapter=chapter, params={"use_llm": False})
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "1")
    start_worker()
    assert worker_status()["max_workers"] == 2
    deadline = time.monotonic() + 8
    last = []
    while time.monotonic() < deadline:
        last = list_jobs(WORK_ID)
        if last and not any(job.get("status") in {"queued", "running"} for job in last):
            break
        time.sleep(0.02)
    stop_worker()
    parses = [job for job in last if job.get("kind") == "parse"]
    assert len(parses) >= 2
    assert all(job["status"] == "done" for job in parses)
    assert peak == 2
