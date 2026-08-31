from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from knowledgehub.catalog import build_catalog
from knowledgehub.edition.read_edition import (
    chapter_document,
    load_chapter,
    load_manifest,
    split_edition_chapters,
)
from knowledgehub.edition.read_edition_steps import parse_micro_chapter, run_macro_step
from knowledgehub.edition.ref import build_read_edition
from knowledgehub.read_edition_service import edition_for_publish
from knowledgehub.server import create_app
from test_catalog import _mini_corpus

FIXTURE = (__import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "grotius_pg_snippet.txt")


def test_split_edition_chapters_from_hints():
    edition, _ = build_read_edition(
        FIXTURE.read_text(encoding="utf-8"),
        family="gutenberg",
        language="en",
        work_id="grotius--freedom_of_the_seas",
    )
    chapters = split_edition_chapters(edition)
    assert chapters
    assert any(c["chapter_id"] != "ch-001" or c.get("split_hint") for c in chapters)
    first = chapter_document(edition, chapters[0])
    assert first["blocks"]
    assert first["reading_markdown"]


def test_two_step_read_edition_package(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    raw_dir = corpus / "sources/grotius/raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "freedom_of_the_seas.txt").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    catalog = corpus / "catalog"
    catalog.mkdir()
    works = [
        {
            "id": "grotius--freedom_of_the_seas",
            "title": "The Freedom of the Seas",
            "author_id": "grotius",
            "language": "en",
            "license": "public_domain_usa_gutenberg",
            "content_file": "sources/grotius/raw/freedom_of_the_seas.txt",
            "content_hash": "deadbeef01",
            "rights": {"consumers": {"read": "allowed"}},
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(json.dumps([{"id": "grotius", "name": "Grotius"}]), encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.setenv("KNOWLEDGEHUB_REF_LLM_DEFAULT", "0")

    result = run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False)
    assert result["built"] is True
    manifest = result["manifest"]
    assert manifest["pipeline"] == "two_step"
    assert manifest["chapter_count"] >= 1

    package_dir = corpus / result["package_dir"]
    loaded = load_manifest(package_dir)
    assert loaded["work_id"] == "grotius--freedom_of_the_seas"
    ch_id = loaded["chapters"][0]["chapter_id"]
    chapter = parse_micro_chapter("grotius--freedom_of_the_seas", ch_id, corpus=corpus, use_llm=False)
    assert chapter["blocks"]
    chapter = load_chapter(package_dir, ch_id)
    assert chapter["blocks"]

    for row in loaded["chapters"]:
        if row["chapter_id"] != ch_id:
            parse_micro_chapter("grotius--freedom_of_the_seas", row["chapter_id"], corpus=corpus, use_llm=False)

    edition, _report = edition_for_publish("grotius--freedom_of_the_seas", corpus=corpus)
    assert edition["edition_format"] == "ref/1"
    assert edition["blocks"]

    result2 = run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False)
    assert result2["built"] is False


@pytest.fixture
def client(tmp_path, monkeypatch):
    corpus = _mini_corpus(tmp_path)
    build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    monkeypatch.setenv("KNOWLEDGEHUB_REF_LLM_DEFAULT", "0")
    return TestClient(create_app())


def test_read_edition_api(client):
    wid = "locke--second_treatise"
    status = client.get(f"/api/works/{wid}/read-edition")
    assert status.status_code == 200
    body = status.json()
    assert body["work_id"] == wid
    assert body.get("macro_complete") is False

    macro = client.post(f"/api/works/{wid}/read-edition/macro", json={"use_llm": False})
    assert macro.status_code == 200
    assert macro.json()["manifest"]["chapter_count"] >= 1

    manifest = client.get(f"/api/works/{wid}/read-edition/manifest")
    assert manifest.status_code == 200
    ch_id = manifest.json()["manifest"]["chapters"][0]["chapter_id"]

    preview = client.get(f"/api/works/{wid}/read-edition/chapters/{ch_id}")
    assert preview.status_code == 200
    assert preview.json().get("micro_status") == "pending"

    parsed = client.post(f"/api/works/{wid}/read-edition/chapters/{ch_id}/parse", json={"use_llm": False})
    assert parsed.status_code == 200
    assert parsed.json()["blocks"]

    chapter = client.get(f"/api/works/{wid}/read-edition/chapters/{ch_id}")
    assert chapter.status_code == 200
    assert chapter.json()["blocks"]

    qa = client.post(f"/api/works/{wid}/read-edition/qa", json={"chapter_id": ch_id, "use_llm": False})
    assert qa.status_code == 200
    assert "passed" in qa.json()


def test_publish_rejects_incomplete_edition(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    raw_dir = corpus / "sources/grotius/raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "freedom_of_the_seas.txt").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    catalog = corpus / "catalog"
    catalog.mkdir()
    works = [
        {
            "id": "grotius--freedom_of_the_seas",
            "title": "The Freedom of the Seas",
            "author_id": "grotius",
            "language": "en",
            "license": "public_domain_usa_gutenberg",
            "content_file": "sources/grotius/raw/freedom_of_the_seas.txt",
            "content_hash": "deadbeef01",
            "rights": {"consumers": {"read": "allowed"}},
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(json.dumps([{"id": "grotius", "name": "Grotius"}]), encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.setenv("KNOWLEDGEHUB_REF_LLM_DEFAULT", "0")

    from knowledgehub.read_publish import PublishError, prepare_publish

    run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False)
    manifest = load_manifest(corpus / "read-editions/grotius--freedom_of_the_seas/deadbeef01")
    parse_micro_chapter("grotius--freedom_of_the_seas", manifest["chapters"][0]["chapter_id"], corpus=corpus, use_llm=False)
    with pytest.raises(PublishError, match="incomplete"):
        prepare_publish("grotius--freedom_of_the_seas", corpus=corpus)


def test_publish_uses_read_edition_package(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    raw_dir = corpus / "sources/grotius/raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "freedom_of_the_seas.txt").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    catalog = corpus / "catalog"
    catalog.mkdir()
    works = [
        {
            "id": "grotius--freedom_of_the_seas",
            "title": "The Freedom of the Seas",
            "author_id": "grotius",
            "language": "en",
            "license": "public_domain_usa_gutenberg",
            "content_file": "sources/grotius/raw/freedom_of_the_seas.txt",
            "content_hash": "deadbeef01",
            "rights": {"consumers": {"read": "allowed"}},
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(json.dumps([{"id": "grotius", "name": "Grotius"}]), encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.setenv("KNOWLEDGEHUB_REF_LLM_DEFAULT", "0")

    from knowledgehub.read_publish import prepare_publish

    run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False)
    manifest = load_manifest(
        corpus / "read-editions/grotius--freedom_of_the_seas/deadbeef01"
    )
    for row in manifest["chapters"]:
        parse_micro_chapter("grotius--freedom_of_the_seas", row["chapter_id"], corpus=corpus, use_llm=False)
    payload = prepare_publish("grotius--freedom_of_the_seas", corpus=corpus)
    assert payload["edition_format"] == "ref/1"
    assert payload.get("_normalize", {}).get("read_edition")
