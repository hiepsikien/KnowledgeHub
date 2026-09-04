from __future__ import annotations

import json

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
    assert "Đang làm" in home.text
    assert "Bắt đầu sách khác" in home.text
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
    assert client.get("/assets/missing--work/plate.png").status_code == 404
    assert client.get("/assets/locke--second_treatise/..png").status_code == 404
    assert client.get("/assets/locke--second_treatise/notes.txt").status_code == 404


def test_ingest_images_requires_gutenberg_id(client):
    res = client.post("/api/works/locke--second_treatise/ingest-images")
    assert res.status_code == 400
    assert "gutenberg_id" in res.json()["detail"]
    missing = client.post("/api/works/nope--missing/ingest-images")
    assert missing.status_code == 404


def test_ingest_images_endpoint_downloads(tmp_path, monkeypatch):
    corpus = _mini_corpus(tmp_path)
    src = corpus / "sources" / "locke" / "works.json"
    rows = json.loads(src.read_text(encoding="utf-8"))
    rows[0]["gutenberg_id"] = "43650"
    src.write_text(json.dumps(rows), encoding="utf-8")
    build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    html = b'<img src="images/illoa001.png" alt="Bach" />'

    def fake_fetch(url: str, **_kwargs) -> bytes:
        if url.endswith(".htm"):
            return html
        return png

    monkeypatch.setattr("knowledgehub.edition.figures._fetch_bytes", fake_fetch)
    from knowledgehub.server import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    res = client.post("/api/works/locke--second_treatise/ingest-images")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["copied"][0]["file"] == "illoa001.png"
    dest = corpus / "assets" / "locke--second_treatise" / "illoa001.png"
    assert dest.read_bytes() == png


def test_list_work_assets_empty_when_none_downloaded(client):
    res = client.get("/api/works/locke--second_treatise/assets")
    assert res.status_code == 200
    body = res.json()
    assert body["work_id"] == "locke--second_treatise"
    assert body["files"] == []
    assert body["total"] == 0
    missing = client.get("/api/works/nope--missing/assets")
    assert missing.status_code == 404


def test_final_touch_attach_asset_without_reparse(tmp_path, monkeypatch):
    corpus = _mini_corpus(tmp_path)
    dest = corpus / "assets" / "locke--second_treatise"
    dest.mkdir(parents=True)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    (dest / "plate.png").write_bytes(png)
    (dest / "_html_figures.json").write_text(
        '[{"file": "plate.png", "alt": "Plate", "caption": "Frontispiece"}]',
        encoding="utf-8",
    )
    build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    monkeypatch.setenv("KNOWLEDGEHUB_REF_LLM_DEFAULT", "0")
    bootstrap_read_edition("locke--second_treatise", corpus=corpus)
    from knowledgehub.server import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    listed = client.get("/api/works/locke--second_treatise/assets")
    assert listed.status_code == 200
    files = listed.json()["files"]
    assert files[0]["file"] == "plate.png"
    assert files[0]["src"] == "/assets/locke--second_treatise/plate.png"

    manifest = client.get("/api/works/locke--second_treatise/read-edition/manifest")
    assert manifest.status_code == 200
    ch_id = manifest.json()["manifest"]["chapters"][0]["chapter_id"]
    chapter = client.get(f"/api/works/locke--second_treatise/read-edition/chapters/{ch_id}")
    assert chapter.status_code == 200
    block = next(b for b in chapter.json()["blocks"] if b.get("type") == "paragraph" and b.get("text"))
    bid = block["block_id"]
    original_text = block["text"]

    missing = client.patch(
        f"/api/works/locke--second_treatise/read-edition/chapters/{ch_id}",
        json={
            "block_patches": [
                {"action": "set_src", "block_id": bid, "src": "missing.png"},
            ]
        },
    )
    assert missing.status_code == 400

    patched = client.patch(
        f"/api/works/locke--second_treatise/read-edition/chapters/{ch_id}",
        json={
            "block_patches": [
                {
                    "action": "set_src",
                    "block_id": bid,
                    "type": "paragraph",
                    "role": "figure",
                    "src": "/assets/locke--second_treatise/plate.png",
                }
            ]
        },
    )
    assert patched.status_code == 200, patched.text
    fig = next(b for b in patched.json()["blocks"] if b["block_id"] == bid)
    assert fig["role"] == "figure"
    assert fig["src"] == "/assets/locke--second_treatise/plate.png"
    assert fig["text"] == original_text

    reloaded = client.get(f"/api/works/locke--second_treatise/read-edition/chapters/{ch_id}")
    fig2 = next(b for b in reloaded.json()["blocks"] if b["block_id"] == bid)
    assert fig2["src"] == "/assets/locke--second_treatise/plate.png"
    assert fig2["role"] == "figure"

    bound = client.post(
        f"/api/works/locke--second_treatise/read-edition/chapters/{ch_id}/bind-assets"
    )
    assert bound.status_code == 200
    assert bound.json()["bound"] == 0
    still = next(b for b in bound.json()["blocks"] if b["block_id"] == bid)
    assert still["src"] == "/assets/locke--second_treatise/plate.png"

    cleared = client.patch(
        f"/api/works/locke--second_treatise/read-edition/chapters/{ch_id}",
        json={"block_patches": [{"action": "set_src", "block_id": bid, "src": ""}]},
    )
    assert cleared.status_code == 200
    gone = next(b for b in cleared.json()["blocks"] if b["block_id"] == bid)
    assert gone.get("src") == ""
    assert gone["role"] == "figure"


def test_work_asset_dir_rejects_traversal(tmp_path):
    from knowledgehub.edition.figures import work_asset_dir

    with pytest.raises(ValueError):
        work_asset_dir(tmp_path, "..")
    with pytest.raises(ValueError):
        work_asset_dir(tmp_path, ".")


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
