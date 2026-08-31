from __future__ import annotations

from pathlib import Path

import pytest

from knowledgehub.edition.macro import build_macro_structure, scan_heading_candidates
from knowledgehub.edition.macro_markers import resolve_division_level, try_marker_assembly
from knowledgehub.edition.macro_qa import detect_body_markers, extract_title_page_toc, extract_toc_from_raw, parse_title_page_entries
from knowledgehub.edition.pipeline import build_edition
from knowledgehub.edition.toc import (
    chapter_number_key,
    is_body_heading_line,
    is_toc_list_row,
    parse_contents_entries,
    toc_is_wrap_page_column,
    toc_match_covers_structure,
    match_toc_entries_in_body,
)


def test_body_heading_not_toc_list_row():
    assert is_body_heading_line("CHAPTER II.")
    assert not is_toc_list_row("CHAPTER II.")
    assert is_toc_list_row("CHAPTER II .... 12")


def test_scan_heading_prefers_body_chapter():
    text = "CONTENTS\nCHAPTER I .... 1\n\nCHAPTER I\n\nBody starts here.\n\nCHAPTER II.\n\nMore.\n"
    cands = scan_heading_candidates(text, language="en")
    by_line = {int(c["line"]): c["heuristic"] for c in cands}
    assert by_line.get(3) == "heading"
    assert by_line.get(7) == "heading"


def _abdy_toc_and_body() -> tuple[str, str]:
    raw = """Title page

Preface

The actual preface paragraph about Bach's family.

Contents


                                                                     PAGE

 PREFACE                                                                v


 CHAPTER I

 The Bachs of Thuringia--Veit Bach, the ancestor of John Sebastian--His
 sons and descendants--A sixteenth century _quodlibet_      1


 CHAPTER II

 Bach’s attitude towards art--His birth--The death of his father       20


 CHAPTER XIV

 Bach as Familien-Vater--Portraits--Public monuments                  170

 CATALOGUE OF VOCAL WORKS                                             177

 CATALOGUE OF INSTRUMENTAL WORKS                                      191

 BIBLIOGRAPHY                                                         202

 GLOSSARY                                                             205


List of Illustrations

  PORTRAIT OF BACH                                     21


Chapter I

    The Bachs of Thuringia--Veit Bach.

John Sebastian Bach came of a large family.

Chapter II

    Bach’s attitude towards art.

He was born at Eisenach.

Chapter XIV

    Bach as Familien-Vater.

He was never a poor man.

Catalogue of Bach’s Vocal Works

  Matthew Passion.

Catalogue of Instrumental Works

  Organ works.

Bibliography

  Spitta.

Glossary

  Ahle, Joh. Rudolph.
"""
    return raw, raw  # strip-less fixture: body headings sit after TOC


def test_parse_abdy_style_wrapped_toc():
    raw, _ = _abdy_toc_and_body()
    entries = parse_contents_entries(raw)
    labels = [e["label"] for e in entries]
    kinds = [e["kind"] for e in entries]
    assert labels[0] == "PREFACE"
    assert "CHAPTER I" in labels
    assert "CHAPTER XIV" in labels
    assert "CATALOGUE OF VOCAL WORKS" in labels
    assert "GLOSSARY" in labels
    assert kinds.count("chapter") == 3
    assert kinds[-1] == "back_matter"
    excerpt = extract_toc_from_raw(raw)
    assert "CHAPTER I" in excerpt
    assert "GLOSSARY" in excerpt
    assert "quodlibet" in excerpt.lower() or "Bachs of Thuringia" in excerpt


def test_macro_uses_toc_for_abdy_style_sections():
    raw, text = _abdy_toc_and_body()
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] == "toc_match"
    titles = [s["title"] for s in doc["sections"]]
    kinds = [s["kind"] for s in doc["sections"]]
    assert "Preface" in titles
    assert "Chapter I" in titles
    assert "Chapter XIV" in titles
    assert any("Vocal" in t for t in titles)
    assert "Bibliography" in titles
    assert "Glossary" in titles
    assert "preface" in kinds
    assert kinds.count("chapter") == 3
    assert kinds.count("back_matter") == 4


def test_macro_abdy_williams_full_pg():
    raw_path = Path("/tmp/pg_full/pg43650.txt")
    if not raw_path.is_file():
        pytest.skip("PG cache missing")
    raw = raw_path.read_text(encoding="utf-8", errors="replace")
    text, _ = build_edition(raw, language="en", strip_only=True)
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] == "toc_match"
    kinds = [s["kind"] for s in doc["sections"]]
    titles = [s["title"] for s in doc["sections"]]
    assert kinds.count("chapter") == 14
    assert "preface" in kinds
    assert kinds.count("back_matter") == 4
    assert any("Chapter XIV" == t or t.endswith("XIV") for t in titles)
    assert any("Glossary" in t for t in titles)
    assert not any(t.startswith("CHAPTER III") for t in titles)  # leftover TOC row


def test_marker_assembly_austen():
    raw = Path("/tmp/pg_full/pg1342.txt")
    if not raw.is_file():
        pytest.skip("PG cache missing")
    text, _ = build_edition(raw.read_text(encoding="utf-8"), language="en", strip_only=True)
    markers = detect_body_markers(text)
    doc = try_marker_assembly(text, markers, language="en")
    assert doc is not None
    assert doc["section_count"] >= 62
    assert doc["mode"] == "markers"


def test_title_page_toc_paine():
    raw = Path("/tmp/pg_full/pg147.txt")
    if not raw.is_file():
        pytest.skip("PG cache missing")
    toc = extract_title_page_toc(raw.read_text(encoding="utf-8"))
    assert "Monarchy" in toc
    assert len(parse_title_page_entries(raw.read_text(encoding="utf-8"))) >= 4


def test_build_macro_structure_markers_path_austen():
    raw = Path("/tmp/pg_full/pg1342.txt")
    if not raw.is_file():
        pytest.skip("PG cache missing")
    text, _ = build_edition(raw.read_text(encoding="utf-8"), language="en", strip_only=True)
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False)
    assert doc["mode"] == "markers"
    assert doc["section_count"] >= 62


def test_resolve_division_level_aristotle():
    raw = Path("/tmp/pg_full/pg6762.txt")
    if not raw.is_file():
        pytest.skip("PG cache missing")
    text, _ = build_edition(raw.read_text(encoding="utf-8"), language="en", strip_only=True)
    markers = detect_body_markers(text)
    assert resolve_division_level(markers) == "chapter"


def test_chapter_number_key_roman_equals_arabic():
    assert chapter_number_key("CHAPTER I") == "1"
    assert chapter_number_key("Chapter 1") == "1"
    assert chapter_number_key("CHAPTER XIV") == chapter_number_key("Chapter 14") == "14"
    assert chapter_number_key("Chap. IV.") == "4"


def _austen_style_one_line_toc() -> str:
    return """Title page

CONTENTS

CHAPTER I.     Mr. Bennet sees Bingley          1
CHAPTER II.    Visit to Netherfield             8
CHAPTER III.   The assembly                    15
CHAPTER IV.    Jane's letter                   22
CHAPTER V.     The ball                        30

Chapter 1

It is a truth universally acknowledged.

Chapter 2

Mr. Bennet was among the earliest of those who waited.

Chapter 3

Not all that Mrs. Bennet, however, with the assistance of her five daughters.

Chapter 4

When Jane and Elizabeth were alone.

Chapter 5

The village of Longbourn was only one mile from Meryton.
"""


def test_one_line_contents_is_not_wrap_page_column():
    entries = parse_contents_entries(_austen_style_one_line_toc())
    assert len(entries) >= 5
    assert all(not e.get("wrapped") for e in entries)
    assert not toc_is_wrap_page_column(entries)


def test_macro_keeps_markers_for_austen_style_one_line_toc():
    text = _austen_style_one_line_toc()
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=text)
    assert doc["mode"] == "markers"
    kinds = [s["kind"] for s in doc["sections"]]
    assert kinds.count("chapter") == 5


def test_all_caps_body_chapter_not_ingested_as_toc():
    raw = """Title

Contents


                                                                     PAGE

 CHAPTER I

 The Bachs of Thuringia--Veit Bach, the ancestor of John Sebastian     1


 CHAPTER II

 Bach’s attitude towards art--His birth                                20


 CHAPTER III

 The organ works at Weimar                                            40


CHAPTER I

John Sebastian Bach came of a large family of musicians in Thuringia who
were known throughout the district.

CHAPTER II

He was born at Eisenach in 1685 and orphaned while still a boy.

CHAPTER III

At Weimar he wrote the greater number of his organ works.
"""
    entries = parse_contents_entries(raw)
    labels = [e["label"] for e in entries]
    assert labels == ["CHAPTER I", "CHAPTER II", "CHAPTER III"]
    joined = " ".join(e.get("title") or "" for e in entries)
    assert "large family of musicians" not in joined
    assert "orphaned while still a boy" not in joined
    doc = build_macro_structure(raw, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] == "toc_match"
    titles = [s["title"] for s in doc["sections"]]
    kinds = [s["kind"] for s in doc["sections"]]
    assert titles.count("CHAPTER I") == 1
    assert kinds.count("chapter") == 3


def test_partial_toc_match_does_not_win():
    raw = """Title

Contents


                                                                     PAGE

 CHAPTER I

 The Bachs of Thuringia--Veit Bach                                     1


 CHAPTER II

 Bach’s attitude towards art                                           20


 CHAPTER III

 The organ works at Weimar                                            40


Chapter I

Body of chapter one continues without a chapter two heading.

Chapter III

Body of chapter three. Chapter II is missing so a 70% rule would still win.
"""
    entries = parse_contents_entries(raw)
    matched = match_toc_entries_in_body(raw, entries)
    assert toc_is_wrap_page_column(entries)
    assert len(matched) == 2
    assert not toc_match_covers_structure(entries, matched)
    doc = build_macro_structure(raw, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] != "toc_match"


def test_toc_match_maps_roman_chapter_to_arabic_body():
    raw = """Title

Contents


                                                                     PAGE

 CHAPTER I

 The Bachs of Thuringia--Veit Bach                                     1


 CHAPTER II

 Bach’s attitude towards art                                           20


 CHAPTER III

 The organ works at Weimar                                            40


Chapter 1

John Sebastian Bach came of a large family.

Chapter 2

He was born at Eisenach.

Chapter 3

At Weimar he wrote for the organ.
"""
    entries = parse_contents_entries(raw)
    matched = match_toc_entries_in_body(raw, entries)
    assert toc_is_wrap_page_column(entries)
    assert toc_match_covers_structure(entries, matched)
    doc = build_macro_structure(raw, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] == "toc_match"
    titles = [s["title"] for s in doc["sections"]]
    assert "Chapter 1" in titles
    assert "Chapter 2" in titles
    assert "Chapter 3" in titles


def test_build_macro_structure_markers_path_grotius():
    raw_path = Path("/tmp/pg_full/pg75962.txt")
    if not raw_path.is_file():
        pytest.skip("PG cache missing")
    text, _ = build_edition(raw_path.read_text(encoding="utf-8"), language="en", strip_only=True)
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False)
    assert doc["mode"] == "markers"
    assert [s["kind"] for s in doc["sections"]].count("chapter") >= 10
