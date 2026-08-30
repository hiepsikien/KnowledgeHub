from __future__ import annotations

import json

import pytest

from knowledgehub.edition.macro import build_macro_structure, scan_heading_candidates
from knowledgehub.edition.read_edition_steps import (
    load_structure,
    parse_micro_chapter,
    run_macro_step,
)

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
