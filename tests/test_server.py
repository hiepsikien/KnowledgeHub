from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knowledgehub.catalog import build_catalog
from knowledgehub.server import create_app
from read_edition_helpers import bootstrap_read_edition
from test_catalog import _mini_corpus


@pytest.fixture
def client(tmp_path, monkeypatch):
    corpus = _mini_corpus(tmp_path)
    build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    bootstrap_read_edition("locke--second_treatise", corpus=corpus)
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
    assert works[0]["can_translate"] is True
    assert works[0]["has_translation_project"] is False
    assert "Dịch sách khác" in home.text
    assert "Pilot: Grotius" not in home.text


def test_create_translation_from_works_list(client):
    created = client.post(
        "/api/translations",
        json={"source_work_id": "locke--second_treatise", "mode": "tight"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["project"]["translation_mode"] == "tight"
    assert body["chapters"][0]["chapter"] == "1"
    summary = client.get("/api/works/locke--second_treatise").json()["summary"]
    assert summary["has_translation_project"] is True
    assert summary["translation_source_id"] == "locke--second_treatise"


def test_preview_normalized_without_allow(client):
    wid = "locke--second_treatise"
    preview = client.get(f"/api/works/{wid}/preview")
    assert preview.status_code == 200
    data = preview.json()
    assert data["truncated"] is False
    assert data["normalize"]["origin"] == "read_edition"
    assert not data["normalize"].get("incomplete")
    text = data.get("text") or ""
    assert "civil government" in text.lower()
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


def test_asset_route_serves_ingested_image(tmp_path, monkeypatch):
    corpus = _mini_corpus(tmp_path)
    dest = corpus / "assets" / "locke--second_treatise"
    dest.mkdir(parents=True)
    (dest / "plate.png").write_bytes(b"png-bytes")
    build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    from knowledgehub.server import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    res = client.get("/assets/locke--second_treatise/plate.png")
    assert res.status_code == 200
    assert res.content == b"png-bytes"
    missing = client.get("/assets/locke--second_treatise/nope.png")
    assert missing.status_code == 404


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
