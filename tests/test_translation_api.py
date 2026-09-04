from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from knowledgehub.server import create_app
from knowledgehub.translation.project import init_translation_project, select_translation_mode
from knowledgehub.translation.providers import ProviderError


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
            "id": "grotius--freedom_of_the_seas",
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
    init_translation_project("grotius--freedom_of_the_seas")
    sample = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode("grotius--freedom_of_the_seas", "tight")
    chi = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    chi_payload = json.loads(chi.read_text(encoding="utf-8"))
    chi_payload["qa"] = {
        "scores": {"fidelity": 8, "fluency": 9, "terminology": 8, "completeness": 10, "overall": 8},
        "summary_vi": "Tốt.",
        "issues": [],
    }
    chi.write_text(json.dumps(chi_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ann = tmp_path / "translations/grotius--freedom_of_the_seas/annotations.json"
    ann.write_text(
        json.dumps(
            {
                "annotations": [
                    {
                        "id": "grotius--freedom_of_the_seas--chi--fn-1",
                        "chapter": "I",
                        "kind": "footnote",
                        "marker": "[1]",
                        "title_vi": "Chú thích [1]",
                        "body_vi": "Pliny.",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return TestClient(create_app())


def test_translation_page_route(client: TestClient):
    page = client.get("/translation/grotius--freedom_of_the_seas/I")
    assert page.status_code == 200
    assert "Dịch thuật" in page.text
    assert 'id="tr-sessions"' in page.text
    assert 'id="tr-pick"' in page.text
    list_page = client.get("/translation")
    assert list_page.status_code == 200
    assert "Đang làm" in list_page.text
    assert "Bắt đầu sách khác" in list_page.text


def test_translation_list_and_project(client: TestClient):
    listed = client.get("/api/translations").json()
    assert listed["total"] == 1
    assert {row["id"] for row in listed["modes"]} == {"tight", "normal", "loose"}
    assert listed["default_mode"] in {"tight", "normal", "loose"}
    assert listed["projects"][0]["source_work_id"] == "grotius--freedom_of_the_seas"
    assert listed["projects"][0]["translation_work_id"] == "grotius--freedom_of_the_seas_vi"
    assert listed["projects"][0]["ready_to_promote"] is False
    assert listed["projects"][0]["mode_label"] == "Sát nguyên bản"
    project = client.get("/api/translations/grotius--freedom_of_the_seas").json()
    assert project["project"]["translation_mode"] == "tight"
    assert len(project["chapters"]) == 2
    ch_i = next(c for c in project["chapters"] if c["chapter"] == "I")
    assert ch_i["qa_overall"] == 8
    assert ch_i["has_final"] is True
    assert ch_i["has_draft_raw"] is False
    assert ch_i["annotation_count"] == 1
    assert ch_i["title_vi"] == "Chương 1"


def test_translation_segment_and_annotations(client: TestClient):
    seg = client.get("/api/translations/grotius--freedom_of_the_seas/segments/I").json()
    assert seg["translation"] == "Bản dịch tight."
    assert "draft_raw_text" in seg
    assert seg["qa"]["scores"]["overall"] == 8
    ann = client.get("/api/translations/grotius--freedom_of_the_seas/annotations?chapter=I").json()
    assert ann["total"] == 1
    assert ann["annotations"][0]["marker"] == "[1]"


def test_translation_qa_endpoint(client: TestClient):
    qa_json = json.dumps(
        {
            "scores": {
                "fidelity": 9,
                "fluency": 9,
                "terminology": 9,
                "completeness": 10,
                "overall": 9,
            },
            "summary_vi": "Rất tốt.",
            "issues": [],
        }
    )
    with patch("knowledgehub.translation.api.qa_segment") as mock_qa:
        mock_qa.return_value = {"scores": {"overall": 9}, "summary_vi": "Rất tốt."}
        res = client.post("/api/translations/grotius--freedom_of_the_seas/qa/I")
    assert res.status_code == 200
    mock_qa.assert_called_once_with("grotius--freedom_of_the_seas", "I")


def test_translation_approve_qa_all(client: TestClient, tmp_path: Path):
    chi = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["qa"]["issues"] = [
        {"severity": "minor", "category": "terminology", "note_vi": "A"},
        {"severity": "minor", "category": "fidelity", "note_vi": "B"},
    ]
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    res = client.post(
        "/api/translations/grotius--freedom_of_the_seas/qa/I/approve",
        json={"all": True},
    )
    assert res.status_code == 200, res.text
    assert res.json()["open_issue_count"] == 0
    one = client.post(
        "/api/translations/grotius--freedom_of_the_seas/qa/I/approve",
        json={"index": 0},
    )
    assert one.status_code == 200


def test_translation_approve_qa_with_replacement(client: TestClient, tmp_path: Path):
    chi = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["final"] = "ngu muội hay kém cỏi"
    payload["drafts"]["tight"] = payload["final"]
    payload["qa"]["issues"] = [
        {
            "severity": "minor",
            "category": "fidelity",
            "note_vi": "unthinking",
            "translation_excerpt": "ngu muội hay kém cỏi",
        }
    ]
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    res = client.post(
        "/api/translations/grotius--freedom_of_the_seas/qa/I/approve",
        json={"index": 0, "replacement": "ngu muội hay thiếu suy nghĩ"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["applied_count"] == 1
    stored = json.loads(chi.read_text(encoding="utf-8"))
    assert stored["final"] == "ngu muội hay thiếu suy nghĩ"


def test_translation_reopen_qa_all(client: TestClient, tmp_path: Path):
    chi = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["qa"]["issues"] = [
        {"severity": "minor", "category": "terminology", "note_vi": "A", "approved": True},
        {"severity": "minor", "category": "fidelity", "note_vi": "B", "approved": True},
    ]
    payload["qa"]["open_issue_count"] = 0
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    res = client.post(
        "/api/translations/grotius--freedom_of_the_seas/qa/I/reopen",
        json={"all": True},
    )
    assert res.status_code == 200, res.text
    assert res.json()["open_issue_count"] == 2
    stored = json.loads(chi.read_text(encoding="utf-8"))
    assert all(not issue.get("approved") for issue in stored["qa"]["issues"])


def test_translation_approve_qa_missing_excerpt_is_400(client: TestClient, tmp_path: Path):
    chi = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["qa"]["issues"] = [
        {
            "severity": "minor",
            "category": "fidelity",
            "note_vi": "A",
            "translation_excerpt": "không có",
        }
    ]
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    res = client.post(
        "/api/translations/grotius--freedom_of_the_seas/qa/I/approve",
        json={"index": 0, "replacement": "câu mới"},
    )
    assert res.status_code == 400
    assert "Không thấy đoạn VI" in res.json()["detail"]
    stored = json.loads(chi.read_text(encoding="utf-8"))
    assert stored["qa"]["issues"][0].get("approved") is not True


def test_translation_qa_provider_error(client: TestClient):
    with patch(
        "knowledgehub.translation.api.qa_segment",
        side_effect=ProviderError("DEEPSEEK_API_KEY is not set"),
    ):
        res = client.post("/api/translations/grotius--freedom_of_the_seas/qa/I")
    assert res.status_code == 400
    assert "DEEPSEEK_API_KEY" in res.json()["detail"]


def test_translation_draft_endpoint(client: TestClient):
    with patch("knowledgehub.translation.api.draft_chapter") as mock_draft:
        mock_draft.return_value = {"chapter": "II", "final_chars": 12, "status": "draft_ready"}
        res = client.post("/api/translations/grotius--freedom_of_the_seas/draft/II")
    assert res.status_code == 200
    mock_draft.assert_called_once_with("grotius--freedom_of_the_seas", chapter="II")


def test_translation_rejects_unsafe_work_id(client: TestClient):
    res = client.get("/api/translations/foo..bar")
    assert res.status_code == 400


def test_translation_annotate_endpoint(client: TestClient):
    with patch("knowledgehub.translation.api.annotate_segment") as mock_ann:
        mock_ann.return_value = {"added_or_updated": 1, "total": 1}
        res = client.post("/api/translations/grotius--freedom_of_the_seas/annotate/I")
    assert res.status_code == 200
    mock_ann.assert_called_once_with("grotius--freedom_of_the_seas", "I")


def test_promote_rejects_incomplete(client: TestClient):
    res = client.post("/api/translations/grotius--freedom_of_the_seas/promote", json={})
    assert res.status_code == 400
    assert "Missing final" in res.json()["detail"]


def test_truncated_final_is_not_ready(client: TestClient):
    from knowledgehub.paths import corpus_root

    path = corpus_root() / "translations/grotius--freedom_of_the_seas/segments/chii.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["final"] = "Đây là một bản dịch bị cắt giữa câu và thiếu phần còn lại r"
    payload["status"] = "draft_ready"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    project = client.get("/api/translations/grotius--freedom_of_the_seas").json()
    ch_ii = next(row for row in project["chapters"] if row["chapter"] == "II")
    assert ch_ii["completeness"] == "truncated"
    assert ch_ii["has_final"] is False
    assert "II" in project["missing_chapters"]
    seg = client.get("/api/translations/grotius--freedom_of_the_seas/segments/II").json()
    assert "bị cắt" in seg["translation"]
    assert "draft_raw_text" in seg


def test_chapter_last_error_from_failed_job(client: TestClient):
    from knowledgehub.translation.jobs import complete_job, enqueue_job

    job = enqueue_job("grotius--freedom_of_the_seas", "II", "draft")
    complete_job(job["id"], error='HTTP 503: {"error":{"message":"high demand","status":"UNAVAILABLE"}}')
    project = client.get("/api/translations/grotius--freedom_of_the_seas").json()
    ch_ii = next(row for row in project["chapters"] if row["chapter"] == "II")
    assert "503" in ch_ii["last_error"]
    assert ch_ii["last_error_kind"] == "draft"
    assert ch_ii["last_error_status"] == "error"
    assert ch_ii["jobs"] == []


def test_last_error_clears_after_later_success(client: TestClient):
    from knowledgehub.translation.jobs import complete_job, enqueue_job

    failed = enqueue_job("grotius--freedom_of_the_seas", "II", "draft")
    complete_job(failed["id"], error="HTTP 503: high demand")
    later = enqueue_job("grotius--freedom_of_the_seas", "II", "draft")
    complete_job(later["id"], result={"chapter": "II", "status": "draft_ready"})
    follow = enqueue_job("grotius--freedom_of_the_seas", "II", "annotate")
    project = client.get("/api/translations/grotius--freedom_of_the_seas").json()
    ch_ii = next(row for row in project["chapters"] if row["chapter"] == "II")
    assert "last_error" not in ch_ii
    assert ch_ii["jobs"][0]["id"] == follow["id"]


def test_last_error_hidden_when_newer_job_queued(client: TestClient):
    from knowledgehub.translation.jobs import complete_job, enqueue_job

    failed = enqueue_job("grotius--freedom_of_the_seas", "II", "annotate")
    complete_job(failed["id"], error="HTTP 429: RESOURCE_EXHAUSTED generate_content_free_tier_requests")
    later = enqueue_job("grotius--freedom_of_the_seas", "II", "draft")
    project = client.get("/api/translations/grotius--freedom_of_the_seas").json()
    ch_ii = next(row for row in project["chapters"] if row["chapter"] == "II")
    assert "last_error" not in ch_ii
    assert ch_ii["jobs"][0]["id"] == later["id"]


def test_last_error_kind_follows_failed_annotate(client: TestClient):
    from knowledgehub.paths import corpus_root
    from knowledgehub.translation.jobs import complete_job, enqueue_job

    draft = enqueue_job("grotius--freedom_of_the_seas", "II", "draft")
    complete_job(draft["id"], result={"chapter": "II", "status": "draft_ready"})
    annotate = enqueue_job("grotius--freedom_of_the_seas", "II", "annotate")
    complete_job(annotate["id"], error="HTTP 429: RESOURCE_EXHAUSTED generate_content_free_tier_requests")
    store_path = corpus_root() / ".translation-jobs.json"
    store = json.loads(store_path.read_text(encoding="utf-8"))
    for job in store["jobs"]:
        if job.get("id") == annotate["id"]:
            job["created_at"] = "2099-01-01T00:00:00+00:00"
            job["finished_at"] = "2099-01-01T00:00:01+00:00"
    store_path.write_text(json.dumps(store), encoding="utf-8")
    project = client.get("/api/translations/grotius--freedom_of_the_seas").json()
    ch_ii = next(row for row in project["chapters"] if row["chapter"] == "II")
    assert "429" in ch_ii["last_error"]
    assert ch_ii["last_error_kind"] == "annotate"
    assert ch_ii["last_error_status"] == "error"


def test_interrupted_qa_shows_until_later_scores(client: TestClient, tmp_path: Path):
    from knowledgehub.translation.jobs import claim_next, enqueue_job, interrupt_stale_running

    enqueue_job("grotius--freedom_of_the_seas", "II", "qa")
    assert claim_next()["status"] == "running"
    assert interrupt_stale_running() == 1
    project = client.get("/api/translations/grotius--freedom_of_the_seas").json()
    ch_ii = next(row for row in project["chapters"] if row["chapter"] == "II")
    assert "interrupted" in ch_ii["last_error"]
    assert ch_ii["last_error_kind"] == "qa"
    assert ch_ii["last_error_status"] == "interrupted"

    path = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chii.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["qa"] = {
        "scores": {"overall": 8},
        "issues": [],
        "completed_at": "2099-01-01T00:00:00+00:00",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    project = client.get("/api/translations/grotius--freedom_of_the_seas").json()
    ch_ii = next(row for row in project["chapters"] if row["chapter"] == "II")
    assert "last_error" not in ch_ii
    assert ch_ii["qa_overall"] == 8


def test_enqueue_draft_job_and_dedupe(client: TestClient):
    first = client.post(
        "/api/translations/grotius--freedom_of_the_seas/jobs",
        json={"kind": "draft", "chapter": "II"},
    )
    assert first.status_code == 200, first.text
    job = first.json()["job"]
    assert job["status"] == "queued"
    assert job["created"] is True
    second = client.post(
        "/api/translations/grotius--freedom_of_the_seas/jobs",
        json={"kind": "draft", "chapter": "II"},
    )
    assert second.status_code == 200
    assert second.json()["job"]["id"] == job["id"]
    assert second.json()["job"]["created"] is False
    listed = client.get("/api/translations/grotius--freedom_of_the_seas/jobs").json()
    assert listed["worker_alive"] is False
    assert listed["workers"]["alive"] == 0
    assert listed["workers"]["min_workers"] == 1
    assert listed["workers"]["max_workers"] == 2
    assert any(row["id"] == job["id"] for row in listed["jobs"])
    project = client.get("/api/translations/grotius--freedom_of_the_seas").json()
    ch_ii = next(row for row in project["chapters"] if row["chapter"] == "II")
    assert ch_ii["jobs"][0]["kind"] == "draft"


def test_enqueue_missing_drafts(client: TestClient):
    res = client.post(
        "/api/translations/grotius--freedom_of_the_seas/jobs",
        json={"kind": "draft", "missing": True},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "II" in body["missing"]
    assert body["enqueued"] >= 1
    assert body["log"]
    assert any(row["event"] == "enqueue_missing" for row in body["log"])
    listed = client.get("/api/translations/grotius--freedom_of_the_seas/jobs").json()
    assert listed["log"]
    assert "workers" in listed


def test_process_next_job_runs_draft(client: TestClient, tmp_path: Path):
    from knowledgehub.translation.jobs import enqueue_job, process_next_job

    enqueue_job("grotius--freedom_of_the_seas", "II", "draft")
    with patch("knowledgehub.translation.draft.draft_chapter") as mock_draft:
        mock_draft.return_value = {"chapter": "II", "final_chars": 12, "status": "draft_ready"}
        done = process_next_job()
    assert done["status"] == "done"
    mock_draft.assert_called_once_with("grotius--freedom_of_the_seas", chapter="II")
    store = json.loads((tmp_path / ".translation-jobs.json").read_text(encoding="utf-8"))
    draft_job = next(job for job in store["jobs"] if job["kind"] == "draft")
    assert draft_job["status"] == "done"
    follow = next(job for job in store["jobs"] if job["kind"] == "annotate")
    assert follow["status"] == "queued"
    assert follow["chapter"] == "II"


def test_claim_next_skips_busy_chapter_but_runs_others(client: TestClient):
    from knowledgehub.translation.jobs import claim_next, complete_job, enqueue_job

    first = enqueue_job("grotius--freedom_of_the_seas", "II", "draft")
    enqueue_job("grotius--freedom_of_the_seas", "II", "qa")
    enqueue_job("grotius--freedom_of_the_seas", "I", "draft")
    claimed = claim_next()
    assert claimed["id"] == first["id"]
    other = claim_next()
    assert other["chapter"] == "I"
    assert claim_next() is None
    complete_job(claimed["id"], result={"ok": True})
    waiting = claim_next()
    assert waiting["chapter"] == "II"
    assert waiting["kind"] == "qa"


def test_claim_next_respects_draft_annotate_qa_order(client: TestClient):
    from knowledgehub.translation.jobs import claim_next, enqueue_job

    enqueue_job("grotius--freedom_of_the_seas", "II", "qa")
    enqueue_job("grotius--freedom_of_the_seas", "II", "annotate")
    draft = enqueue_job("grotius--freedom_of_the_seas", "I", "draft")
    first = claim_next()
    assert first["id"] == draft["id"]
    assert first["kind"] == "draft"
    second = claim_next()
    assert second["kind"] == "annotate"
    assert second["chapter"] == "II"
    assert claim_next() is None


def test_cancel_running_job_skips_followups(client: TestClient, tmp_path: Path):
    from knowledgehub.translation.jobs import cancel_jobs, enqueue_job, process_next_job, report_progress

    enqueue_job("grotius--freedom_of_the_seas", "II", "draft")

    def fake_draft(*_args, **_kwargs):
        report_progress("drafting", "Đang gọi DeepSeek nháp…")
        cancel_jobs(source_work_id="grotius--freedom_of_the_seas", chapter="II")
        from knowledgehub.translation.jobs import raise_if_stopped

        raise_if_stopped()
        return {"chapter": "II"}

    with patch("knowledgehub.translation.draft.draft_chapter", side_effect=fake_draft):
        done = process_next_job()
    assert done["status"] == "cancelled"
    store = json.loads((tmp_path / ".translation-jobs.json").read_text(encoding="utf-8"))
    kinds = [job["kind"] for job in store["jobs"]]
    assert "annotate" not in kinds
    draft = next(job for job in store["jobs"] if job["kind"] == "draft")
    assert draft["status"] == "cancelled"
    assert draft["phase"] == "cancelled"


def test_interrupt_stale_running_does_not_requeue(client: TestClient, tmp_path: Path):
    from knowledgehub.translation.jobs import claim_next, enqueue_job, interrupt_stale_running

    enqueue_job("grotius--freedom_of_the_seas", "II", "draft")
    claimed = claim_next()
    assert claimed["status"] == "running"
    n = interrupt_stale_running()
    assert n == 1
    store = json.loads((tmp_path / ".translation-jobs.json").read_text(encoding="utf-8"))
    job = store["jobs"][0]
    assert job["status"] == "interrupted"
    assert claim_next() is None


def test_cancel_jobs_api(client: TestClient):
    queued = client.post(
        "/api/translations/grotius--freedom_of_the_seas/jobs",
        json={"kind": "draft", "chapter": "II"},
    )
    assert queued.status_code == 200
    cancelled = client.post(
        "/api/translations/grotius--freedom_of_the_seas/jobs/cancel",
        json={"chapter": "II"},
    )
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["cancelled"] == 1
    listed = client.get("/api/translations/grotius--freedom_of_the_seas/jobs").json()
    assert listed["jobs"][0]["status"] == "cancelled"


def test_progress_phase_written(client: TestClient, tmp_path: Path):
    from knowledgehub.translation.jobs import enqueue_job, process_next_job, report_progress

    enqueue_job("grotius--freedom_of_the_seas", "II", "draft")

    def fake_draft(*_args, **_kwargs):
        report_progress("drafting", "Đang gọi DeepSeek nháp…")
        return {"chapter": "II"}

    with (
        patch("knowledgehub.translation.draft.draft_chapter", side_effect=fake_draft),
        patch("knowledgehub.translation.annotate.annotate_segment", return_value={"added_or_updated": 0}),
        patch("knowledgehub.translation.qa.qa_segment", return_value={"scores": {"overall": 8}}),
    ):
        done = process_next_job()
    assert done["status"] == "done"
    store = json.loads((tmp_path / ".translation-jobs.json").read_text(encoding="utf-8"))
    draft = next(job for job in store["jobs"] if job["kind"] == "draft")
    assert draft["phase"] == "done"
    assert "attempts" in draft


def test_create_translation_from_catalog(client: TestClient, tmp_path: Path):
    sources = tmp_path / "sources/locke/raw"
    sources.mkdir(parents=True)
    (sources / "second_treatise.txt").write_text("Of civil government.\n" * 12, encoding="utf-8")
    works_path = tmp_path / "catalog/works.json"
    works = json.loads(works_path.read_text(encoding="utf-8"))
    works.append(
        {
            "id": "locke--second_treatise",
            "title": "Second Treatise of Government",
            "author_id": "locke",
            "language": "en",
            "content_file": "sources/locke/raw/second_treatise.txt",
        }
    )
    works_path.write_text(json.dumps(works), encoding="utf-8")

    listed = client.get("/api/works").json()["works"]
    grotius = next(row for row in listed if row["id"] == "grotius--freedom_of_the_seas")
    locke = next(row for row in listed if row["id"] == "locke--second_treatise")
    assert grotius["has_translation_project"] is True
    assert grotius["can_translate"] is True
    assert locke["can_translate"] is True
    assert locke["has_translation_project"] is False

    exists = client.post(
        "/api/translations",
        json={"source_work_id": "grotius--freedom_of_the_seas", "mode": "tight"},
    )
    assert exists.status_code == 409

    created = client.post(
        "/api/translations",
        json={"source_work_id": "locke--second_treatise", "mode": "loose"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["created"] is True
    assert body["project"]["translation_mode"] == "loose"
    assert body["project"]["status"] == "mode_locked"
    assert len(body["chapters"]) == 1
    assert body["chapters"][0]["chapter"] == "1"
    assert not (tmp_path / "translations/locke--second_treatise/segments/chi-sample.json").exists()

    page = client.get("/")
    assert "Đang làm" in page.text
    assert "Bắt đầu sách khác" in page.text
    assert "Pilot: Grotius" not in page.text


def test_create_recovers_incomplete_translation_dir(client: TestClient, tmp_path: Path):
    project = tmp_path / "translations/grotius--freedom_of_the_seas/project.json"
    project.unlink()
    listed = client.get("/api/translations").json()
    assert listed["total"] == 0
    missing = client.get("/api/translations/grotius--freedom_of_the_seas")
    assert missing.status_code == 404
    created = client.post(
        "/api/translations",
        json={"source_work_id": "grotius--freedom_of_the_seas", "mode": "normal"},
    )
    assert created.status_code == 200
    assert created.json()["project"]["translation_mode"] == "normal"
    assert created.json()["project"]["status"] == "mode_locked"


def test_create_recovers_project_json_without_chapters(client: TestClient, tmp_path: Path):
    root = tmp_path / "translations/grotius--freedom_of_the_seas"
    for path in (root / "segments").glob("ch*.json"):
        path.unlink()
    listed = client.get("/api/translations").json()
    assert listed["total"] == 0
    missing = client.get("/api/translations/grotius--freedom_of_the_seas")
    assert missing.status_code == 404
    created = client.post(
        "/api/translations",
        json={"source_work_id": "grotius--freedom_of_the_seas", "mode": "normal"},
    )
    assert created.status_code == 200
    assert created.json()["created"] is True
    assert (root / "segments/chi.json").is_file()


def test_get_translation_does_not_write_titles(client: TestClient, tmp_path: Path):
    chi = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload.pop("title_vi", None)
    payload["final"] = "Bản nháp đang chạy."
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    before = chi.read_text(encoding="utf-8")
    project = client.get("/api/translations/grotius--freedom_of_the_seas").json()
    ch_i = next(c for c in project["chapters"] if c["chapter"] == "I")
    assert ch_i["title_vi"] == "Chương 1"
    after = json.loads(chi.read_text(encoding="utf-8"))
    assert chi.read_text(encoding="utf-8") == before
    assert "title_vi" not in after
    assert after["final"] == "Bản nháp đang chạy."
