from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from knowledgehub.server import create_app
from knowledgehub.settings import clamp_worker_limits, followup_kinds, resolve_models, save_settings
from knowledgehub.translation.jobs import desired_worker_count, enqueue_job, process_next_job
from knowledgehub.translation.project import init_translation_project, select_translation_mode
from knowledgehub.translation.providers import (
    ProviderError,
    clear_model_catalog_cache,
    complete_chat,
    list_available_models,
    list_deepseek_models,
    list_gemini_models,
    provider_for_model,
)

FAKE_CATALOG = {
    "models": [
        {"id": "deepseek-chat", "label": "DeepSeek Chat", "provider": "deepseek"},
        {"id": "deepseek-reasoner", "label": "DeepSeek Reasoner", "provider": "deepseek"},
        {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash", "provider": "deepseek"},
        {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash", "provider": "gemini"},
        {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro", "provider": "gemini"},
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "provider": "gemini"},
    ],
    "errors": {},
    "fetched_at": "2026-08-28T00:00:00+00:00",
    "counts": {"deepseek": 3, "gemini": 3},
}


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
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    monkeypatch.setattr(
        "knowledgehub.translation.providers.list_available_models",
        lambda refresh=False: FAKE_CATALOG,
    )
    init_translation_project("grotius--freedom_of_the_seas")
    sample = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode("grotius--freedom_of_the_seas", "tight")
    return TestClient(create_app())


def test_settings_page(client: TestClient):
    page = client.get("/settings")
    assert page.status_code == 200
    assert "Cài đặt Hub" in page.text
    assert "Tải lại danh sách" in page.text
    assert "min_workers" in page.text
    assert "max_workers" in page.text
    assert "max_attempts" in page.text
    assert "job_timeout_sec" in page.text
    assert "max_part_words" in page.text
    assert 'id="set-max-part-words"' in page.text
    assert 'value="1200"' in page.text
    assert 'id="set-hard-max-part-words"' in page.text
    assert 'value="1500"' in page.text
    assert "Chế bản (REF)" in page.text
    assert 'id="set-llm-macro"' in page.text
    assert ">Chế bản<" in page.text


def test_settings_get_defaults(client: TestClient):
    data = client.get("/api/settings").json()
    tr = data["settings"]["translation"]
    assert tr["auto_annotate"] is True
    assert tr["auto_qa"] is True
    assert tr["min_workers"] == 1
    assert tr["max_workers"] == 2
    assert tr["max_attempts"] == 2
    assert tr["job_timeout_sec"] == 600
    assert tr["max_part_words"] == 1200
    assert tr["hard_max_part_words"] == 1500
    assert tr["models"]["draft"] == "deepseek-v4-flash"
    assert tr["models"]["qa"] == "deepseek-v4-pro"
    ids = {m["id"] for m in data["model_catalog"]}
    assert "deepseek-v4-flash" in ids
    assert "gemini-2.5-pro" in ids
    assert data["model_catalog_counts"]["deepseek"] == 3
    assert data["secrets"]["gemini"] is True
    assert data["secrets"]["deepseek"] is False
    ed = data["settings"]["edition"]
    assert ed["use_llm_macro"] is True
    assert ed["use_llm_relabel"] is True
    assert ed["use_llm_qa"] is True


def test_settings_save_edition_llm_flags(client: TestClient, tmp_path: Path):
    res = client.post(
        "/api/settings",
        json={"edition": {"use_llm_macro": False, "use_llm_relabel": True, "use_llm_qa": False}},
    )
    assert res.status_code == 200, res.text
    ed = res.json()["settings"]["edition"]
    assert ed["use_llm_macro"] is False
    assert ed["use_llm_relabel"] is True
    assert ed["use_llm_qa"] is False
    stored = json.loads((tmp_path / "hub-settings.json").read_text(encoding="utf-8"))
    assert stored["edition"]["use_llm_macro"] is False
    again = client.post("/api/settings", json={"translation": {"auto_qa": False}})
    assert again.status_code == 200
    kept = again.json()["settings"]["edition"]
    assert kept["use_llm_macro"] is False
    assert kept["use_llm_qa"] is False


def test_settings_save_models_and_pipeline(client: TestClient, tmp_path: Path):
    res = client.post(
        "/api/settings",
        json={
            "translation": {
                "models": {
                    "draft": "deepseek-reasoner",
                    "polish": "gemini-2.5-pro",
                    "qa": "gemini-3.5-flash",
                    "annotations": "deepseek-chat",
                },
                "auto_annotate": False,
                "auto_qa": True,
                "default_mode": "tight",
                "min_workers": 1,
                "max_workers": 3,
            }
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    tr = body["settings"]["translation"]
    assert tr["models"]["draft"] == "deepseek-reasoner"
    assert tr["models"]["polish"] == "gemini-2.5-pro"
    assert tr["auto_annotate"] is False
    assert tr["auto_qa"] is True
    assert tr["default_mode"] == "tight"
    assert tr["min_workers"] == 1
    assert tr["max_workers"] == 3
    assert body["projects_updated"] == 1
    stored = json.loads((tmp_path / "hub-settings.json").read_text(encoding="utf-8"))
    assert stored["translation"]["models"]["qa"] == "gemini-3.5-flash"
    project = json.loads(
        (tmp_path / "translations/grotius--freedom_of_the_seas/project.json").read_text(encoding="utf-8")
    )
    assert project["models"]["draft"] == "deepseek-reasoner"
    pipeline = client.get("/api/translations/grotius--freedom_of_the_seas").json()["pipeline"]
    assert pipeline["auto_annotate"] is False
    assert pipeline["auto_qa"] is True
    assert pipeline["models"]["polish"] == "gemini-2.5-pro"
    assert pipeline["min_workers"] == 1
    assert pipeline["max_workers"] == 3


def test_settings_saves_part_word_limits(client: TestClient, tmp_path: Path):
    res = client.post(
        "/api/settings",
        json={"translation": {"max_part_words": 900, "hard_max_part_words": 1100}},
    )
    assert res.status_code == 200, res.text
    tr = res.json()["settings"]["translation"]
    assert tr["max_part_words"] == 900
    assert tr["hard_max_part_words"] == 1100
    again = client.get("/api/settings").json()["settings"]["translation"]
    assert again["max_part_words"] == 900
    assert again["hard_max_part_words"] == 1100
    stored = json.loads((tmp_path / "hub-settings.json").read_text(encoding="utf-8"))
    assert stored["translation"]["max_part_words"] == 900
    assert stored["translation"]["hard_max_part_words"] == 1100


def test_settings_saves_call_limits(client: TestClient, tmp_path: Path):
    res = client.post(
        "/api/settings",
        json={"translation": {"llm_retries": 4, "gemini_rpm": 8, "deepseek_rpm": 50}},
    )
    assert res.status_code == 200, res.text
    tr = res.json()["settings"]["translation"]
    assert (tr["llm_retries"], tr["gemini_rpm"], tr["deepseek_rpm"]) == (4, 8, 50)
    again = client.get("/api/settings").json()["settings"]["translation"]
    assert (again["llm_retries"], again["gemini_rpm"], again["deepseek_rpm"]) == (4, 8, 50)
    stored = json.loads((tmp_path / "hub-settings.json").read_text(encoding="utf-8"))
    assert stored["translation"]["gemini_rpm"] == 8


def test_settings_page_has_call_limit_fields(client: TestClient):
    html = client.get("/settings").text
    assert 'id="set-llm-retries"' in html
    assert 'id="set-gemini-rpm"' in html
    assert 'id="set-deepseek-rpm"' in html


def test_settings_clamps_worker_limits(client: TestClient):
    res = client.post(
        "/api/settings",
        json={"translation": {"min_workers": 5, "max_workers": 2}},
    )
    assert res.status_code == 200, res.text
    tr = res.json()["settings"]["translation"]
    assert tr["min_workers"] == 2
    assert tr["max_workers"] == 2
    high = client.post(
        "/api/settings",
        json={"translation": {"min_workers": -3, "max_workers": 99}},
    )
    tr = high.json()["settings"]["translation"]
    assert tr["min_workers"] == 0
    assert tr["max_workers"] == 8


def test_clamp_worker_limits():
    assert clamp_worker_limits(1, 2) == (1, 2)
    assert clamp_worker_limits(5, 2) == (2, 2)
    assert clamp_worker_limits(-1, 3) == (0, 3)
    assert clamp_worker_limits(0, 0) == (0, 1)
    assert clamp_worker_limits("1", "4") == (1, 4)


def test_desired_worker_count():
    assert desired_worker_count(0, 0, 1, 2) == 1
    assert desired_worker_count(0, 0, 0, 2) == 0
    assert desired_worker_count(5, 0, 1, 2) == 2
    assert desired_worker_count(1, 1, 1, 2) == 2


def test_settings_rejects_unknown_model(client: TestClient):
    res = client.post(
        "/api/settings",
        json={"translation": {"models": {"draft": "gpt-4o"}}},
    )
    assert res.status_code == 400
    assert "Unknown model provider" in res.json()["detail"]


def test_followup_kinds_order(client: TestClient):
    save_settings({"translation": {"auto_annotate": True, "auto_qa": True}})
    assert followup_kinds("draft") == ["annotate"]
    assert followup_kinds("annotate") == ["qa"]
    assert followup_kinds("qa") == []
    save_settings({"translation": {"auto_annotate": False, "auto_qa": True}})
    assert followup_kinds("draft") == ["qa"]
    save_settings({"translation": {"auto_annotate": False, "auto_qa": False}})
    assert followup_kinds("draft") == []
    assert followup_kinds("annotate") == []


def test_draft_job_queues_annotate_then_qa(client: TestClient, tmp_path: Path):
    save_settings({"translation": {"auto_annotate": True, "auto_qa": True}})
    enqueue_job("grotius--freedom_of_the_seas", "II", "draft")
    with (
        patch("knowledgehub.translation.draft.draft_chapter", return_value={"chapter": "II"}),
        patch("knowledgehub.translation.annotate.annotate_segment", return_value={"added_or_updated": 1}),
        patch("knowledgehub.translation.qa.qa_segment", return_value={"scores": {"overall": 8}}),
    ):
        first = process_next_job()
        assert first["kind"] == "draft"
        assert first["status"] == "done"
        second = process_next_job()
        assert second["kind"] == "annotate"
        assert second["status"] == "done"
        third = process_next_job()
        assert third["kind"] == "qa"
        assert third["status"] == "done"
    store = json.loads((tmp_path / ".translation-jobs.json").read_text(encoding="utf-8"))
    kinds = [job["kind"] for job in store["jobs"]]
    assert kinds.count("draft") == 1
    assert kinds.count("annotate") == 1
    assert kinds.count("qa") == 1


def test_annotate_error_still_queues_qa(client: TestClient, tmp_path: Path):
    save_settings(
        {"translation": {"auto_annotate": True, "auto_qa": True, "max_attempts": 1}}
    )
    enqueue_job("grotius--freedom_of_the_seas", "II", "annotate")
    with (
        patch(
            "knowledgehub.translation.annotate.annotate_segment",
            side_effect=RuntimeError("HTTP 429: RESOURCE_EXHAUSTED"),
        ),
        patch("knowledgehub.translation.qa.qa_segment", return_value={"scores": {"overall": 8}}),
    ):
        failed = process_next_job()
        assert failed["kind"] == "annotate"
        assert failed["status"] == "error"
        follow = process_next_job()
        assert follow is not None
        assert follow["kind"] == "qa"
        assert follow["status"] == "done"
    store = json.loads((tmp_path / ".translation-jobs.json").read_text(encoding="utf-8"))
    kinds = [job["kind"] for job in store["jobs"]]
    assert kinds.count("annotate") == 1
    assert kinds.count("qa") == 1


def test_resolve_models_uses_hub_settings(client: TestClient):
    save_settings({"translation": {"models": {"qa": "gemini-2.5-flash"}}})
    models = resolve_models({"models": {"qa": "deepseek-reasoner"}})
    assert models["qa"] == "gemini-2.5-flash"
    assert models["draft"] == "deepseek-v4-flash"


def test_provider_for_model():
    assert provider_for_model("deepseek-chat") == "deepseek"
    assert provider_for_model("gemini-3.5-flash") == "gemini"
    with pytest.raises(ProviderError):
        provider_for_model("gpt-4o")


def test_complete_chat_routes_gemini():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    with patch("knowledgehub.translation.providers.gemini_generate", return_value="ok") as mock_g:
        assert complete_chat(messages, model="gemini-3.5-flash") == "ok"
    mock_g.assert_called_once()
    assert mock_g.call_args.kwargs["model"] == "gemini-3.5-flash"
    assert mock_g.call_args.kwargs["system"] == "sys"


def test_list_deepseek_models_from_api(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    def fake_get(url, headers, *, timeout=20):
        assert url == "https://api.deepseek.com/models"
        assert headers["Authorization"] == "Bearer sk-test"
        return {
            "object": "list",
            "data": [
                {"id": "deepseek-v4-flash", "object": "model", "owned_by": "deepseek"},
                {"id": "deepseek-v4-pro", "object": "model", "owned_by": "deepseek"},
                {"id": "deepseek-v4-flash", "object": "model", "owned_by": "deepseek"},
                {"id": "deepseek-v4-flash-vision-exp", "object": "model", "owned_by": "deepseek"},
            ],
        }

    monkeypatch.setattr("knowledgehub.translation.providers._get_json", fake_get)
    rows = list_deepseek_models()
    assert [row["id"] for row in rows] == ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert rows[0]["label"] == "DeepSeek V4 Flash"
    assert rows[0]["provider"] == "deepseek"


def test_list_gemini_models_filters_non_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-test")

    def fake_get(url, headers, *, timeout=20):
        assert "generativelanguage.googleapis.com/v1beta/models" in url
        assert headers["x-goog-api-key"] == "gem-test"
        return {
            "models": [
                {
                    "name": "models/gemini-2.5-pro",
                    "displayName": "Gemini 2.5 Pro",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-2.5-flash-preview-05-20",
                    "displayName": "Gemini 2.5 Flash Preview",
                    "supportedGenerationMethods": ["generateContent"],
                    "thinking": True,
                },
                {
                    "name": "models/gemini-embedding-001",
                    "displayName": "Gemini Embedding",
                    "supportedGenerationMethods": ["embedContent", "generateContent"],
                },
                {
                    "name": "models/gemini-2.5-flash-image",
                    "displayName": "Nano Banana",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/imagen-4.0-generate",
                    "displayName": "Imagen 4",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/text-embedding-004",
                    "displayName": "Embedding",
                    "supportedGenerationMethods": ["embedContent"],
                },
            ]
        }

    monkeypatch.setattr("knowledgehub.translation.providers._get_json", fake_get)
    rows = list_gemini_models()
    ids = [row["id"] for row in rows]
    assert ids == ["gemini-2.5-pro", "gemini-2.5-flash-preview-05-20"]
    assert rows[0]["label"] == "Gemini 2.5 Pro"
    assert rows[1]["thinking"] is True


def test_list_available_models_reports_provider_errors(monkeypatch: pytest.MonkeyPatch):
    clear_model_catalog_cache()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(
        "knowledgehub.translation.providers.list_deepseek_models",
        lambda: [{"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro", "provider": "deepseek"}],
    )
    live = list_available_models(refresh=True)
    assert live["counts"]["deepseek"] == 1
    assert live["counts"]["gemini"] == 0
    assert "GEMINI_API_KEY" in live["errors"]["gemini"]
    assert live["models"][0]["id"] == "deepseek-v4-pro"
