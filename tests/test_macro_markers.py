from __future__ import annotations

from pathlib import Path

import pytest

from knowledgehub.edition.macro import build_macro_structure, scan_heading_candidates
from knowledgehub.edition.macro_markers import resolve_division_level, try_marker_assembly
from knowledgehub.edition.macro_qa import detect_body_markers, extract_title_page_toc, extract_toc_from_raw, parse_title_page_entries
from knowledgehub.edition.pipeline import build_edition
from knowledgehub.edition.toc import (
    is_body_heading_line,
    is_toc_list_row,
    parse_contents_entries,
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
