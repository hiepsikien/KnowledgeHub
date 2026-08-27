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
    return TestClient(create_app())


def test_ui_and_list(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "Knowledge Hub" in home.text
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


def test_ops_secret_blocks(tmp_path, monkeypatch):
    corpus = _mini_corpus(tmp_path)
    build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.setenv("KNOWLEDGEHUB_OPS_SECRET", "s3cret")
    client = TestClient(create_app())
    assert client.get("/api/works").status_code == 401
    bad = client.post("/api/login", json={"secret": "nope"})
    assert bad.status_code == 401
    ok = client.post("/api/login", json={"secret": "s3cret"})
    assert ok.status_code == 200
    assert client.get("/api/works").status_code == 200
