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
from knowledgehub.read_edition_service import confirm_toc, edition_for_publish, get_review, head_tail_preview
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
    chapter = parse_micro_chapter("grotius--freedom_of_the_seas", ch_id, corpus=corpus, use_llm=False, require_ready=False)
    assert chapter["blocks"]
    chapter = load_chapter(package_dir, ch_id)
    assert chapter["blocks"]

    for row in loaded["chapters"]:
        if row["chapter_id"] != ch_id:
            parse_micro_chapter("grotius--freedom_of_the_seas", row["chapter_id"], corpus=corpus, use_llm=False, require_ready=False)

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


def test_cheban_ui_labels(client):
    page = client.get("/read-edition")
    assert page.status_code == 200
    html = page.text
    assert ">Chế bản<" in html
    assert "Đang làm" in html
    assert "← Đang làm" in html
    assert "Bước 1: Phân đoạn" not in html
    assert "Parse REF chương" not in html
    assert "Parse chương này" in html
    assert "Phân loại lại" in html
    assert "Khôi phục đề xuất" in html
    assert "Đề xuất lại" not in html
    assert "Reset phân đoạn" not in html
    assert ">Reset<" in html
    assert "Chế bản (REF)" in html
    assert 'id="re-section-full"' in html
    assert "Nối dòng" in html
    assert "Chạy thử chương này" in html
    assert "Chạy toàn văn bản" in html
    assert 'data-step="footnotes"' in html
    assert 'data-step="quotes"' in html


def test_toc_reclass_keeps_excerpt_and_reset_wipes(client):
    wid = "locke--second_treatise"
    blocked = client.post(f"/api/works/{wid}/read-edition/macro", json={"keep_toc": True, "use_llm": False})
    assert blocked.status_code == 400

    macro = client.post(f"/api/works/{wid}/read-edition/macro", json={"use_llm": False})
    assert macro.status_code == 200
    edited = "CONTENTS\nCHAPTER I. THE FAMILY OF BACH\nCHAPTER II. THE CAREER OF BACH"
    toc = client.post(f"/api/works/{wid}/read-edition/toc", json={"status": "yes", "excerpt": edited})
    assert toc.status_code == 200
    assert toc.json()["toc_candidate"]["excerpt"] == edited
    assert toc.json()["toc_candidate"]["source"] == "curated"

    reclass = client.post(f"/api/works/{wid}/read-edition/macro", json={"keep_toc": True, "use_llm": False})
    assert reclass.status_code == 200
    hitl_toc = reclass.json()["structure"]["hitl"]["toc"]
    assert hitl_toc["excerpt"] == edited
    assert hitl_toc["status"] == "yes"

    reset = client.post(f"/api/works/{wid}/read-edition/reset")
    assert reset.status_code == 200
    assert reset.json()["reset"] is True
    status = client.get(f"/api/works/{wid}/read-edition")
    assert status.json()["macro_complete"] is False
    review = client.get(f"/api/works/{wid}/read-edition/review")
    assert review.status_code == 400


def test_read_edition_api(client):
    wid = "locke--second_treatise"
    empty = client.get("/api/read-editions")
    assert empty.status_code == 200
    assert empty.json()["sessions"] == []

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
    pending = preview.json()
    assert pending.get("micro_status") == "pending"
    assert "source_preview" in pending
    assert "source_preview_truncated" in pending
    source = client.get(f"/api/works/{wid}/read-edition/chapters/{ch_id}/source")
    assert source.status_code == 200
    src = source.json()
    assert src["chapter_id"] == ch_id
    assert src["text"]
    assert src["chars"] == len(src["text"])
    head = pending.get("source_preview_head") or ""
    if head:
        assert src["text"].startswith(head)
    missing = client.get(f"/api/works/{wid}/read-edition/chapters/no-such-section/source")
    assert missing.status_code == 400
    viewed = client.get(f"/api/works/{wid}/read-edition")
    assert viewed.json()["hitl"]["last_section_id"] == ch_id

    parsed = client.post(f"/api/works/{wid}/read-edition/chapters/{ch_id}/parse", json={"use_llm": False})
    assert parsed.status_code == 400
    detail = parsed.json()["detail"]
    assert "not ready" in str(detail).lower()

    toc = client.post(f"/api/works/{wid}/read-edition/toc", json={"status": "none"})
    assert toc.status_code == 200
    review = client.get(f"/api/works/{wid}/read-edition/review")
    assert review.status_code == 200
    for sid in review.json()["health"]["untreated_flags"]:
        confirmed = client.post(
            f"/api/works/{wid}/read-edition/structure/edit",
            json={"action": "confirm", "section_id": sid},
        )
        assert confirmed.status_code == 200
    blocked = client.post(f"/api/works/{wid}/read-edition/chapters/{ch_id}/parse", json={"use_llm": False})
    assert blocked.status_code == 400
    assert "cấu trúc ok" in str(blocked.json()["detail"]).lower()
    layout = client.post(f"/api/works/{wid}/read-edition/layout")
    assert layout.status_code == 200
    assert layout.json()["health"]["layout_ok"] is True
    assert layout.json()["health"]["ready_to_parse"] is True

    parsed = client.post(f"/api/works/{wid}/read-edition/chapters/{ch_id}/parse", json={"use_llm": False})
    assert parsed.status_code == 200
    assert parsed.json()["blocks"]

    listed = client.get("/api/read-editions")
    assert listed.status_code == 200
    sessions = listed.json()["sessions"]
    assert any(s["work_id"] == wid for s in sessions)
    row = next(s for s in sessions if s["work_id"] == wid)
    assert row["chapters_parsed"] >= 1
    assert row["phase"] in {"parsing", "parsed"}
    assert row["last_section_id"] == ch_id
    assert row["layout_ok"] is True

    status2 = client.get(f"/api/works/{wid}/read-edition")
    assert status2.json()["hitl"]["last_section_id"] == ch_id
    assert status2.json()["phase"] in {"parsing", "parsed"}

    chapter = client.get(f"/api/works/{wid}/read-edition/chapters/{ch_id}")
    assert chapter.status_code == 200
    assert chapter.json()["blocks"]
    source_after = client.get(f"/api/works/{wid}/read-edition/chapters/{ch_id}/source")
    assert source_after.status_code == 200
    assert source_after.json()["chars"] == src["chars"]
    assert source_after.json()["text"] == src["text"]

    qa = client.post(f"/api/works/{wid}/read-edition/qa", json={"chapter_id": ch_id, "use_llm": False})
    assert qa.status_code == 200
    assert "passed" in qa.json()

    review = client.get(f"/api/works/{wid}/read-edition/review")
    assert review.status_code == 200
    payload = review.json()
    assert "toc_candidate" in payload
    assert "health" in payload
    assert "coverage" in payload
    toc = client.post(f"/api/works/{wid}/read-edition/toc", json={"status": "none"})
    assert toc.status_code == 200
    assert toc.json()["toc_candidate"]["status"] == "none"


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
    parse_micro_chapter("grotius--freedom_of_the_seas", manifest["chapters"][0]["chapter_id"], corpus=corpus, use_llm=False, require_ready=False)
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
        parse_micro_chapter("grotius--freedom_of_the_seas", row["chapter_id"], corpus=corpus, use_llm=False, require_ready=False)
    payload = prepare_publish("grotius--freedom_of_the_seas", corpus=corpus)
    assert payload["edition_format"] == "ref/1"
    assert payload.get("_normalize", {}).get("read_edition")


def _grotius_corpus(tmp_path, monkeypatch):
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
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    return corpus


def test_structure_hitl_edit_prunes_stale_chapter_json(tmp_path, monkeypatch):
    corpus = _grotius_corpus(tmp_path, monkeypatch)
    from knowledgehub.edition.read_edition_steps import edit_structure_step
    from knowledgehub.read_edition_service import get_review

    result = run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False)
    chapters = result["manifest"]["chapters"]
    assert len(chapters) >= 2
    first_id = chapters[0]["chapter_id"]
    second_id = chapters[1]["chapter_id"]
    parse_micro_chapter("grotius--freedom_of_the_seas", first_id, corpus=corpus, use_llm=False, require_ready=False)
    parse_micro_chapter("grotius--freedom_of_the_seas", second_id, corpus=corpus, use_llm=False, require_ready=False)
    package_dir = corpus / result["package_dir"]
    assert (package_dir / "chapters" / f"{second_id}.json").is_file()

    review = get_review("grotius--freedom_of_the_seas", corpus=corpus)
    assert "toc_candidate" in review
    assert review["coverage"]["complete"] is True

    edited = edit_structure_step(
        "grotius--freedom_of_the_seas",
        action="merge_prev",
        section_id=second_id,
        corpus=corpus,
    )
    assert edited["structure"]["section_count"] == result["structure"]["section_count"] - 1
    assert not (package_dir / "chapters" / f"{second_id}.json").is_file()
    remaining = list((package_dir / "chapters").glob("*.json"))
    assert remaining == [] or all(
        row.get("micro_status") != "complete"
        for row in edited["manifest"]["chapters"]
    )
    for row in edited["manifest"]["chapters"]:
        assert row.get("micro_status") == "pending"

    toc = confirm_toc("grotius--freedom_of_the_seas", "yes", corpus=corpus)
    assert toc["toc_candidate"]["status"] == "yes"


def test_list_sessions_uses_catalog_hash_without_manuscript(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    catalog = corpus / "catalog"
    catalog.mkdir(parents=True)
    works = [
        {
            "id": "bacon--novum_organum",
            "title": "Novum Organum",
            "author_id": "bacon",
            "language": "en",
            "content_hash": "abc123",
            "content_file": "sources/bacon/raw/novum_organum.txt",
            "rights": {"consumers": {"read": "allowed"}},
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(json.dumps([{"id": "bacon", "name": "Bacon"}]), encoding="utf-8")
    pkg = corpus / "read-editions/bacon--novum_organum/abc123"
    pkg.mkdir(parents=True)
    (pkg / "structure.json").write_text(
        json.dumps(
            {
                "structure_version": "1",
                "sections": [{"section_id": "ch-001", "title": "BOOK I", "kind": "book", "start_line": 0}],
                "section_count": 1,
                "hitl": {"last_section_id": "ch-001", "toc": {"status": "none"}},
                "created_at": "2026-01-01T00:00:00",
                "mode": "markers",
            }
        ),
        encoding="utf-8",
    )
    (pkg / "manifest.json").write_text(
        json.dumps(
            {
                "work_id": "bacon--novum_organum",
                "macro_status": "complete",
                "macro_mode": "markers",
                "updated_at": "2026-01-02T00:00:00",
                "chapters": [{"chapter_id": "ch-001", "micro_status": "pending"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    from knowledgehub.edition.read_edition import list_read_edition_sessions

    sessions = list_read_edition_sessions(corpus=corpus)
    assert len(sessions) == 1
    row = sessions[0]
    assert row["work_id"] == "bacon--novum_organum"
    assert row["last_section_id"] == "ch-001"
    assert row["phase"] == "hitl"
    assert row["chapters_total"] == 1


def test_head_tail_preview_short_text_is_full():
    body = "abc" * 100
    out = head_tail_preview(body)
    assert out["source_preview_truncated"] is False
    assert out["source_preview"] == body
    assert out["source_preview_head"] == body
    assert out["source_preview_tail"] == ""
    assert out["source_preview_omitted"] == 0


def test_head_tail_preview_long_text_keeps_head_and_tail():
    body = ("H" * 2000) + ("M" * 1500) + ("T" * 2000)
    out = head_tail_preview(body)
    assert out["source_preview_truncated"] is True
    assert out["source_preview_head"] == "H" * 2000
    assert out["source_preview_tail"] == "T" * 2000
    assert out["source_preview_omitted"] == 1500
    assert "M" not in out["source_preview_head"]
    assert "M" not in out["source_preview_tail"]
    assert "[… omitted 1500 chars …]" in out["source_preview"]
