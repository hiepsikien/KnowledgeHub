from __future__ import annotations

from pathlib import Path

import pytest

from knowledgehub.edition.macro import build_macro_structure, scan_heading_candidates
from knowledgehub.edition.macro_markers import resolve_division_level, try_marker_assembly
from knowledgehub.edition.macro_qa import detect_body_markers, extract_title_page_toc, parse_title_page_entries
from knowledgehub.edition.pipeline import build_edition
from knowledgehub.edition.toc import is_body_heading_line, is_toc_list_row


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
