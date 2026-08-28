from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from knowledgehub.settings import save_settings
from knowledgehub.translation.jobs import (
    enqueue_job,
    list_jobs,
    start_worker,
    stop_worker,
    worker_status,
)
from knowledgehub.translation.project import init_translation_project, select_translation_mode

WORK_ID = "grotius--freedom_of_the_seas"
CHAPTERS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII")


def _roman_chapters(n: int) -> str:
    numerals = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]
    parts = [f"CHAPTER {numerals[i]}\n\nEnglish paragraph {numerals[i]} one.\n" for i in range(n)]
    return "\n".join(parts)


@pytest.fixture
def pool_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sources = tmp_path / "sources/grotius/raw"
    sources.mkdir(parents=True)
    (sources / "freedom_of_the_seas.txt").write_text(_roman_chapters(8), encoding="utf-8")
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
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    init_translation_project(WORK_ID)
    sample = tmp_path / f"translations/{WORK_ID}/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode(WORK_ID, "tight")
    yield tmp_path
    stop_worker()


def _no_llm(*_args, **_kwargs):
    raise AssertionError("LLM must not be called in worker-pool tests")


def _wait_idle(*, timeout: float = 12.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    last: list[dict] = []
    while time.monotonic() < deadline:
        last = list_jobs(WORK_ID)
        if last and not any(job.get("status") in {"queued", "running"} for job in last):
            return last
        time.sleep(0.02)
    raise AssertionError(
        "jobs did not settle: "
        + ", ".join(f"{job.get('chapter')}/{job.get('kind')}={job.get('status')}" for job in last)
    )


def _install_fake_executor(monkeypatch: pytest.MonkeyPatch, *, parties: int, hold: float):
    lock = threading.Lock()
    current = 0
    peak = 0
    overlap: list[str] = []
    active_chapters: set[str] = set()
    threads: set[str] = set()
    calls: list[tuple[str, str, str]] = []
    barrier = threading.Barrier(parties)

    def fake_execute(job):
        nonlocal current, peak
        chapter = str(job.get("chapter") or "")
        kind = str(job.get("kind") or "")
        name = threading.current_thread().name
        with lock:
            if chapter in active_chapters:
                overlap.append(chapter)
            active_chapters.add(chapter)
            current += 1
            peak = max(peak, current)
            threads.add(name)
            calls.append((chapter, kind, name))
        try:
            barrier.wait(timeout=5)
            time.sleep(hold)
            return {"chapter": chapter, "kind": kind, "ok": True}
        finally:
            with lock:
                current -= 1
                active_chapters.discard(chapter)

    monkeypatch.setattr("knowledgehub.translation.jobs.execute_job", fake_execute)
    monkeypatch.setattr("knowledgehub.translation.providers.complete_chat", _no_llm)
    monkeypatch.setattr("knowledgehub.translation.providers.complete_prompt", _no_llm)
    monkeypatch.setattr("knowledgehub.translation.providers.gemini_generate", _no_llm)
    return {
        "peak": lambda: peak,
        "overlap": overlap,
        "threads": threads,
        "calls": calls,
    }


def test_four_workers_run_drafts_in_parallel(pool_corpus: Path, monkeypatch: pytest.MonkeyPatch):
    save_settings(
        {
            "translation": {
                "min_workers": 1,
                "max_workers": 4,
                "auto_annotate": False,
                "auto_qa": False,
            }
        }
    )
    stats = _install_fake_executor(monkeypatch, parties=4, hold=0.2)
    for chapter in CHAPTERS:
        enqueue_job(WORK_ID, chapter, "draft")

    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "1")
    start_worker()
    assert worker_status()["max_workers"] == 4
    alive = worker_status()["alive"]
    assert alive == 4, f"expected 4 live workers after enqueue, got {alive}"

    jobs = _wait_idle()
    stop_worker()

    drafts = [job for job in jobs if job.get("kind") == "draft"]
    assert len(drafts) == 8
    assert {job["chapter"] for job in drafts} == set(CHAPTERS)
    assert all(job["status"] == "done" for job in drafts)
    assert stats["peak"]() == 4
    assert len(stats["threads"]) == 4
    assert not stats["overlap"]
    assert all(kind == "draft" for _chapter, kind, _name in stats["calls"])
    assert not any(job.get("kind") in {"annotate", "qa"} for job in jobs)


def test_four_workers_pipeline_keeps_chapter_exclusive(pool_corpus: Path, monkeypatch: pytest.MonkeyPatch):
    save_settings(
        {
            "translation": {
                "min_workers": 1,
                "max_workers": 4,
                "auto_annotate": True,
                "auto_qa": True,
            }
        }
    )
    stats = _install_fake_executor(monkeypatch, parties=4, hold=0.12)
    for chapter in CHAPTERS[:4]:
        enqueue_job(WORK_ID, chapter, "draft")

    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "1")
    start_worker()
    jobs = _wait_idle()
    stop_worker()

    by_kind = {}
    for job in jobs:
        by_kind.setdefault(job["kind"], []).append(job)
    assert set(by_kind) == {"draft", "annotate", "qa"}
    for kind, rows in by_kind.items():
        assert {row["chapter"] for row in rows} == set(CHAPTERS[:4]), kind
        assert all(row["status"] == "done" for row in rows), kind
    assert stats["peak"]() == 4
    assert not stats["overlap"]
    for chapter in CHAPTERS[:4]:
        order = [kind for ch, kind, _name in stats["calls"] if ch == chapter]
        assert order == ["draft", "annotate", "qa"], (chapter, order)
