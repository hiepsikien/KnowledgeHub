from __future__ import annotations

import re

import pytest

from knowledgehub.edition.macro import build_macro_structure, scan_heading_candidates
from knowledgehub.edition.macro_profile import (
    collect_profile_context,
    compile_profile_patterns,
    merge_candidates,
    scan_content_matches,
    scan_extended_candidates,
)


def test_scan_extended_finds_roman_section():
    text = "Front\n\nI.\n\nFirst section body here.\n\nII.\n\nSecond section.\n"
    profile = {"heading_rules": [{"pattern": r"^I\.$", "kind": "roman_section"}]}
    cands = scan_extended_candidates(text, profile, language="en")
    lines = {int(c["line"]) for c in cands}
    assert 2 in lines  # I.
    assert 6 in lines  # II.


def test_compile_profile_patterns_skips_invalid():
    profile = {
        "heading_rules": [
            {"pattern": r"^CHAPTER\s+\d+", "kind": "chapter", "flags": "i"},
            {"pattern": r"(?P<bad", "kind": "broken"},
        ]
    }
    compiled = compile_profile_patterns(profile)
    assert len(compiled) == 1


def test_scan_content_matches_toc_labels():
    text = (
        "Front matter\n\n"
        "CHAPTER I\n"
        "The start of things.\n\n"
        "CHAPTER II\n"
        "More story.\n"
    )
    profile = {
        "division_unit": "chapter",
        "toc_body_entries": [
            {"index": 1, "label": "CHAPTER I", "match_strings": ["CHAPTER I"]},
            {"index": 2, "label": "CHAPTER II", "match_strings": ["CHAPTER II"]},
        ],
    }
    matches = scan_content_matches(text, profile, language="en")
    assert len(matches) == 2
    assert matches[0]["heuristic"] == "content_match"


def test_merge_candidates_prefers_content_match():
    a = [{"line": 5, "text": "CHAPTER I", "heuristic": "heading"}]
    b = [{"line": 5, "text": "CHAPTER I", "heuristic": "content_match", "confidence": 0.9}]
    merged = merge_candidates(a, b)
    assert len(merged) == 1
    assert merged[0]["heuristic"] == "content_match"


def test_collect_profile_context_includes_toc():
    raw = "Title\n\nCONTENTS\n\nCHAPTER I .... 1\nCHAPTER II .... 5\n\nCHAPTER I\n\nBody."
    text = "CHAPTER I\n\nBody."
    ctx = collect_profile_context(text, raw, language="en")
    assert "CHAPTER" in (ctx.get("toc_full") or ctx.get("head_excerpt") or "")


def test_build_macro_structure_pa1_without_llm_falls_back():
    text = "Intro\n\nCHAPTER I\n\nOne.\n\nCHAPTER II\n\nTwo.\n"
    doc = build_macro_structure(
        text,
        language="en",
        family="plain",
        use_llm=False,
        strategy="pa1",
        raw=text,
    )
    assert doc["section_count"] >= 2
    assert doc.get("profile_mode") == "pa1"


def test_build_macro_structure_unknown_strategy_raises():
    with pytest.raises(ValueError, match="unknown macro strategy"):
        build_macro_structure("x", strategy="pa99")


def test_should_use_content_bounds_requires_coverage():
    from knowledgehub.edition.macro_profile import _should_use_content_bounds

    profile = {"toc_body_entries": [{"index": i} for i in range(10)]}
    content = [{"line": i} for i in range(2)]
    assert not _should_use_content_bounds(content, profile, expected_body_divisions=5)
    content_ok = [{"line": i} for i in range(9)]
    assert _should_use_content_bounds(content_ok, profile, expected_body_divisions=0)
