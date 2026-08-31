from __future__ import annotations

from knowledgehub.edition.macro import _sections_from_boundaries, build_macro_structure
from knowledgehub.edition.macro_review import (
    apply_structure_edit,
    build_review,
    coverage_report,
    match_toc_line,
    normalize_toc_label,
    propose_toc_candidate,
)


def _book() -> str:
    chunks = ["Title page and imprint.\n"]
    for title in ("CHAPTER I", "CHAPTER II", "CHAPTER III"):
        body = " ".join(["prose"] * 120)
        chunks.append(f"\n{title}\n\n{body}\n")
    return "".join(chunks)


def test_normalize_toc_label_drops_page_numbers():
    assert "12" not in normalize_toc_label("CHAPTER I. Of War ........ 12")
    assert "chapter i" in normalize_toc_label("CHAPTER I. Of War ........ 12")


def test_match_toc_line_fuzzy():
    hit = match_toc_line("CHAPTER I", ["CHAPTER I. Of the sea .... 3", "CHAPTER II. Peace"])
    assert hit is not None
    assert "CHAPTER I" in hit["label"]


def test_coverage_complete_and_gap():
    text = "abcdefghij"
    sections = [{"start_char": 0, "end_char": 9}]
    ok = coverage_report(text, sections)
    assert ok["complete"] is True
    assert ok["orphan_chars"] == 0
    gap = coverage_report(text, [{"start_char": 2, "end_char": 5}])
    assert gap["complete"] is False
    assert gap["orphan_chars"] == 6


def test_propose_toc_from_raw_contents():
    raw = "Title\n\nCONTENTS\n\nCHAPTER I .... 1\nCHAPTER II .... 5\n\n*** START ***\nCHAPTER I\nBody\n"
    text = "CHAPTER I\nBody\n"
    cand = propose_toc_candidate(text, raw)
    assert cand["source"] == "raw"
    assert "CHAPTER I" in cand["excerpt"]
    assert cand["line_count"] >= 2


def test_merge_split_drop_rebuild_contiguous():
    text = _book()
    structure = build_macro_structure(text, language="en", family="plain", use_llm=False)
    assert structure["section_count"] >= 3
    sections = structure["sections"]
    # Use a body chapter, not front matter, so merge_prev is valid.
    body = next(s for s in sections if s.get("kind") != "front_matter")
    idx = sections.index(body)
    if idx == 0:
        # only body sections — merge_next instead
        other = sections[1]
        merged, focus = apply_structure_edit(
            text, structure, action="merge_next", section_id=body["section_id"], language="en"
        )
        assert merged["section_count"] == structure["section_count"] - 1
        assert focus == body["start_line"]
    else:
        merged, focus = apply_structure_edit(
            text, structure, action="merge_prev", section_id=body["section_id"], language="en"
        )
        assert merged["section_count"] == structure["section_count"] - 1
        assert focus == sections[idx - 1]["start_line"]
    cov = coverage_report(text, merged["sections"])
    assert cov["complete"] is True
    starts = [int(s["start_char"]) for s in merged["sections"]]
    assert starts == sorted(starts)
    for left, right in zip(merged["sections"], merged["sections"][1:]):
        assert int(right["start_char"]) == int(left["end_char"]) + 1

    # Split a long section at an inner heading if present
    from knowledgehub.edition.macro_review import inner_heading_candidates

    long_sec = max(merged["sections"], key=lambda s: int(s.get("word_count") or 0))

    heads = inner_heading_candidates(text, long_sec, language="en")
    if heads:
        split, split_focus = apply_structure_edit(
            text,
            merged,
            action="split_at",
            section_id=long_sec["section_id"],
            start_line=heads[0]["line"],
            language="en",
        )
        assert split["section_count"] == merged["section_count"] + 1
        assert split_focus == heads[0]["line"]
        assert coverage_report(text, split["sections"])["complete"] is True
        structure = split
    else:
        structure = merged

    # drop_start on a non-first body section
    secs = structure["sections"]
    if len(secs) >= 2:
        dropped, drop_focus = apply_structure_edit(
            text, structure, action="drop_start", section_id=secs[1]["section_id"], language="en"
        )
        assert dropped["section_count"] == structure["section_count"] - 1
        assert drop_focus == secs[0]["start_line"]
        assert coverage_report(text, dropped["sections"])["complete"] is True


def test_build_review_flags_short_and_inner():
    text = "Intro line.\n\nCHAPTER I\nHi.\n\nCHAPTER II\n" + ("word " * 200) + "\n"
    structure = _sections_from_boundaries(
        text,
        [
            {"start_line": 0, "kind": "front_matter", "title": "Front"},
            {"start_line": 2, "kind": "chapter", "title": "CHAPTER I"},
            {"start_line": 4, "kind": "chapter", "title": "CHAPTER II"},
        ],
        language="en",
    )
    structure["hitl"] = {
        "toc": {
            "excerpt": "CHAPTER I\nCHAPTER II",
            "source": "raw",
            "location": "front",
            "status": "yes",
            "line_count": 2,
        },
        "confirmed_starts": [],
    }
    review = build_review(text, structure, language="en")
    by_title = {s["title"]: s for s in review["sections"]}
    assert "short" in by_title["CHAPTER I"]["flags"]
    assert "toc_hit" in by_title["CHAPTER I"]["flags"]
    assert review["coverage"]["complete"] is True
