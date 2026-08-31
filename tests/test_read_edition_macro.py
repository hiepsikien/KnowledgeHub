from __future__ import annotations

import json

import pytest

from knowledgehub.edition.macro import (
    _normalize_llm_boundaries,
    _sections_from_boundaries,
    build_macro_structure,
    scan_heading_candidates,
)
from knowledgehub.edition.read_edition_steps import (
    ReadEditionStepError,
    assemble_edition_from_package,
    load_structure,
    parse_micro_chapter,
    run_macro_step,
)
from knowledgehub.read_edition_service import edition_for_publish

FIXTURE = (__import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "grotius_pg_snippet.txt")


def test_scan_heading_candidates_finds_chapters():
    text = FIXTURE.read_text(encoding="utf-8")
    candidates = scan_heading_candidates(text, language="en")
    assert candidates
    assert any(c.get("heuristic") == "heading" for c in candidates)


def test_rule_macro_structure_sections():
    text = FIXTURE.read_text(encoding="utf-8")
    structure = build_macro_structure(text, language="en", family="gutenberg", use_llm=False)
    assert structure["section_count"] >= 1
    assert structure["mode"] == "rule"
    sections = structure["sections"]
    assert sections[0]["start_char"] == 0
    for sec in sections:
        assert sec["end_char"] >= sec["start_char"]
        assert sec["section_id"]


def test_run_macro_and_parse_one_chapter(tmp_path, monkeypatch):
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

    macro = run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False)
    assert macro["built"] is True
    package_dir = corpus / macro["package_dir"]
    structure = load_structure(package_dir)
    assert structure is not None
    assert structure["section_count"] >= 1

    ch_id = structure["sections"][0]["section_id"]
    chapter = parse_micro_chapter("grotius--freedom_of_the_seas", ch_id, corpus=corpus, use_llm=False)
    assert chapter["micro_status"] == "complete"
    assert chapter["blocks"]

    macro2 = run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False)
    assert macro2["built"] is False


def test_normalize_llm_boundaries_snaps_near_candidate():
    candidates = [{"line": 10, "text": "CHAPTER I"}, {"line": 50, "text": "CHAPTER II"}]
    boundaries = [{"start_line": 11, "kind": "chapter", "title": "CHAPTER I", "confidence": 0.9}]
    normalized, err = _normalize_llm_boundaries(boundaries, candidates)
    assert err is None
    assert normalized is not None
    assert normalized[0]["start_line"] == 10


def test_normalize_llm_boundaries_rejects_far_line():
    candidates = [{"line": 10, "text": "CHAPTER I"}]
    boundaries = [{"start_line": 99, "kind": "chapter", "title": "X", "confidence": 0.9}]
    normalized, err = _normalize_llm_boundaries(boundaries, candidates)
    assert normalized is None
    assert err


def test_sections_from_boundaries_rejects_unknown_line():
    text = "line zero\nline one\n"
    with pytest.raises(ValueError, match="unknown start_line"):
        _sections_from_boundaries(text, [{"start_line": 99, "kind": "chapter", "title": "X"}], language="en")


def test_force_remacro_resets_parsed_chapters(tmp_path, monkeypatch):
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

    macro = run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False)
    package_dir = corpus / macro["package_dir"]
    structure = load_structure(package_dir)
    for sec in structure["sections"]:
        parse_micro_chapter("grotius--freedom_of_the_seas", sec["section_id"], corpus=corpus, use_llm=False)

    edition_for_publish("grotius--freedom_of_the_seas", corpus=corpus)

    shift_on_next = {"v": True}

    def shifted_macro(text, **kwargs):
        doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False)
        if shift_on_next["v"] and len(doc.get("sections") or []) >= 2:
            shift_on_next["v"] = False
            doc = json.loads(json.dumps(doc))
            secs = doc["sections"]
            secs[1]["start_char"] = int(secs[1]["start_char"]) + 12
            secs[0]["end_char"] = int(secs[1]["start_char"]) - 1
            secs[0]["word_count"] = 1
            secs[1]["word_count"] = 1
        return doc

    monkeypatch.setattr("knowledgehub.edition.read_edition_steps.build_macro_structure", shifted_macro)

    remacro = run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False, force=True)
    manifest = remacro["manifest"]
    assert any(row.get("micro_status") == "pending" for row in manifest["chapters"])
    assert not any((package_dir / "chapters" / f"{row['chapter_id']}.json").is_file() for row in manifest["chapters"])
    with pytest.raises(ReadEditionStepError, match="incomplete"):
        assemble_edition_from_package(
            package_dir,
            language="en",
            source_family="gutenberg",
        )
