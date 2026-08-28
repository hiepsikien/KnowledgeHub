from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knowledgehub.catalog import build_catalog
from knowledgehub.server import create_app
from test_catalog import _mini_corpus


@pytest.fixture
def client(tmp_path, monkeypatch):
    corpus = _mini_corpus(tmp_path)
    build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    return TestClient(create_app())


def test_ui_and_list(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "Knowledge Hub" in home.text
    assert "Cài đặt" in home.text
    stats = client.get("/api/stats").json()
    assert stats["works"] == 1
    works = client.get("/api/works").json()["works"]
    assert works[0]["id"] == "locke--second_treatise"
    assert works[0]["read_allowed"] is False


def test_preview_normalized_without_allow(client):
    wid = "locke--second_treatise"
    preview = client.get(f"/api/works/{wid}/preview")
    assert preview.status_code == 200
    data = preview.json()
    assert data["truncated"] is False
    assert data["text"].startswith("Of civil government")
    assert data["normalize"]["source_chars"] > 0


def test_allow_and_dry_publish(client):
    wid = "locke--second_treatise"
    blocked = client.post(f"/api/works/{wid}/publish-read", json={"apply": False})
    assert blocked.status_code == 400
    allowed = client.post(f"/api/works/{wid}/allow-read", json={"allowed": True})
    assert allowed.status_code == 200
    assert allowed.json()["summary"]["read_allowed"] is True
    dry = client.post(f"/api/works/{wid}/publish-read", json={"apply": False})
    assert dry.status_code == 200
    assert dry.json()["dry_run"] is True
    assert dry.json()["payload"]["hub_work_id"] == wid


def test_publish_page_and_overrides(client):
    wid = "locke--second_treatise"
    page = client.get(f"/publish/{wid}")
    assert page.status_code == 200
    assert "Publish to Read" in page.text
    opts = client.get("/api/read-options").json()
    assert any(c["slug"] == "essays" for c in opts["categories"])
    assert {row["value"] for row in opts["split_lengths"]} == {"short", "standard", "long"}
    client.post(f"/api/works/{wid}/allow-read", json={"allowed": True})
    dry = client.post(
        f"/api/works/{wid}/publish-read",
        json={
            "apply": False,
            "persist": True,
            "title": "Second Treatise",
            "description": "Property and government.",
            "category_slug": "essays",
            "price_cents": 0,
            "split_length": "long",
        },
    )
    assert dry.status_code == 200
    payload = dry.json()["payload"]
    assert payload["split_length"] == "long"
    assert payload["description"] == "Property and government."
    stored = client.get(f"/api/works/{wid}").json()
    assert stored["work"]["read"]["split_length"] == "long"


def test_ops_secret_blocks(tmp_path, monkeypatch):
    corpus = _mini_corpus(tmp_path)
    build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    monkeypatch.setenv("KNOWLEDGEHUB_OPS_SECRET", "s3cret")
    client = TestClient(create_app())
    assert client.get("/api/works").status_code == 401
    bad = client.post("/api/login", json={"secret": "nope"})
    assert bad.status_code == 401
    ok = client.post("/api/login", json={"secret": "s3cret"})
    assert ok.status_code == 200
    assert client.get("/api/works").status_code == 200


def test_static_rejects_path_traversal(client):
    for path in (
        "/%2e%2e/translation/providers.py",
        "/%2e%2e/%2e%2e/%2e%2e/.env",
        "/..%2ftranslation/providers.py",
    ):
        leaked = client.get(path)
        assert leaked.status_code == 404, path
        assert "class ProviderError" not in leaked.text
        assert "DEEPSEEK_API_KEY" not in leaked.text
    spa = client.get("/../translation/providers.py")
    assert "class ProviderError" not in spa.text
    js = client.get("/app.js")
    assert js.status_code == 200
    assert "boot()" in js.text
    assert js.headers.get("cache-control") == "no-store"
