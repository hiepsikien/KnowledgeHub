from __future__ import annotations

import pytest

from knowledgehub.edition.ref import build_read_edition
from knowledgehub.edition.serialize import blocks_to_markdown
from knowledgehub.grotius_extract import extract_english_treatise
from knowledgehub.normalize import normalize_manuscript


FIXTURE = (__import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "grotius_pg_snippet.txt")


def test_grotius_snippet_joins_wrapped_prose():
    raw = FIXTURE.read_text(encoding="utf-8")
    edition, report = build_read_edition(
        raw,
        family="gutenberg",
        language="en",
        work_id="grotius--freedom_of_the_seas",
    )
    md = edition["reading_markdown"]
    assert edition["edition_format"] == "ref/1"
    assert report["block_count"] >= 8
    assert "that the Dutch have the right to sail to the East Indies." in md
    assert "destroy this most praise-worthy bond of human fellowship." in md
    assert "societatem." in md
    block_types = [b["type"] for b in edition["blocks"]]
    assert "blockquote" in block_types
    assert block_types.count("hr") >= 2
    hints = edition["split_hints"]
    assert any("CHAPTER I" in str(h.get("text") or "") for h in hints)
    assert any("CHAPTER II" in str(h.get("text") or "") for h in hints)


def test_grotius_chapter_subtitle_is_heading():
    raw = FIXTURE.read_text(encoding="utf-8")
    edition, _ = build_read_edition(
        raw,
        family="gutenberg",
        language="en",
        work_id="grotius--freedom_of_the_seas",
    )
    headings = [b for b in edition["blocks"] if b["type"] == "heading"]
    assert any("_By the Law of Nations" in b.get("text", "") for b in headings)


def test_normalize_attaches_ref_edition(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    raw_dir = corpus / "sources/grotius/raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "freedom_of_the_seas.txt").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    catalog = corpus / "catalog"
    catalog.mkdir()
    import json

    works = [
        {
            "id": "grotius--freedom_of_the_seas",
            "title": "The Freedom of the Seas",
            "author_id": "grotius",
            "language": "en",
            "license": "public_domain_usa_gutenberg",
            "content_file": "sources/grotius/raw/freedom_of_the_seas.txt",
            "content_hash": "deadbeef",
            "rights": {"consumers": {"read": "allowed"}},
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(json.dumps([{"id": "grotius", "name": "Grotius"}]), encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))

    from knowledgehub.read_publish import prepare_publish
    from read_edition_helpers import bootstrap_read_edition

    bootstrap_read_edition("grotius--freedom_of_the_seas", corpus=corpus)
    payload = prepare_publish("grotius--freedom_of_the_seas", corpus=corpus)
    assert payload["edition_format"] == "ref/1"
    assert payload["edition_hash"]
    assert payload["blocks"]
    assert "Dutch have the right" in payload["raw_text"]
    cache = corpus / "editions/grotius--freedom_of_the_seas/deadbeef/blocks.json"
    assert cache.is_file()


def test_extract_english_treatise_sample():
    bilingual = (
        "*** START OF THE PROJECT GUTENBERG EBOOK DEMO ***\n\n"
        "INTRODUCTORY NOTE\n\n"
        "CHAPTER I\n\n"
        + FIXTURE.read_text(encoding="utf-8")
        + "\n\nINDEX\n\nAeneas, 12\n"
        + "*** END OF THE PROJECT GUTENBERG EBOOK DEMO ***\n"
    )
    english, stats = extract_english_treatise(bilingual)
    assert stats["chapters"] >= 2
    edition, _ = build_read_edition(
        english,
        family="gutenberg",
        language="en",
        work_id="grotius--freedom_of_the_seas",
    )
    assert blocks_to_markdown(edition["blocks"]) == edition["reading_markdown"]
