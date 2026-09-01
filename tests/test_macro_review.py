from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledgehub.edition.macro import _sections_from_boundaries, build_macro_structure
from knowledgehub.edition.macro_review import (
    apply_structure_edit,
    build_review,
    coverage_report,
    match_toc_line,
    normalize_toc_label,
    propose_toc_candidate,
)
from knowledgehub.edition.read_edition_steps import (
    ReadEditionStepError,
    confirm_layout_step,
    edit_structure_step,
    parse_micro_chapter,
    run_macro_step,
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
    assert hit["label"].startswith("CHAPTER I")
    assert "CHAPTER II" not in hit["label"]


def test_match_toc_line_does_not_confuse_roman_i_and_ii():
    assert match_toc_line("CHAPTER I", ["CHAPTER II. Peace", "CHAPTER III. War"]) is None
    hit = match_toc_line("CHAPTER II", ["CHAPTER I. Sea", "CHAPTER II. Peace", "CHAPTER III. War"])
    assert hit is not None
    assert "CHAPTER II" in hit["label"]
    assert hit["label"] != "CHAPTER III. War"


def test_coverage_complete_and_gap():
    text = "abcdefghij"
    sections = [{"start_char": 0, "end_char": 9}]
    ok = coverage_report(text, sections)
    assert ok["complete"] is True
    assert ok["orphan_chars"] == 0
    gap = coverage_report(text, [{"start_char": 2, "end_char": 5}])
    assert gap["complete"] is False
    assert gap["orphan_chars"] == 6


def test_coverage_overlap_spans_shared_chars():
    text = "abcdefghij"
    report = coverage_report(
        text,
        [{"start_char": 0, "end_char": 6}, {"start_char": 4, "end_char": 9}],
    )
    assert report["complete"] is False
    assert report["overlaps"] == [{"start_char": 4, "end_char": 6}]


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
    body = next(s for s in sections if s.get("kind") != "front_matter")
    idx = sections.index(body)
    if idx == 0:
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

    lines = text.split("\n")
    ch1 = lines.index("CHAPTER I")
    ch2 = lines.index("CHAPTER II")
    ch3 = lines.index("CHAPTER III")
    host_structure = _sections_from_boundaries(
        text,
        [
            {"start_line": 0, "kind": "front_matter", "title": "Front"},
            {"start_line": ch1, "kind": "chapter", "title": "CHAPTER I"},
            {"start_line": ch3, "kind": "chapter", "title": "CHAPTER III"},
        ],
        language="en",
    )
    host = next(s for s in host_structure["sections"] if s["title"] == "CHAPTER I")
    split, split_focus = apply_structure_edit(
        text,
        host_structure,
        action="split_at",
        section_id=host["section_id"],
        start_line=ch2,
        language="en",
    )
    assert split["section_count"] == host_structure["section_count"] + 1
    assert split_focus == ch2
    assert coverage_report(text, split["sections"])["complete"] is True
    titles = [s["title"] for s in split["sections"]]
    assert any("CHAPTER II" in t for t in titles)

    secs = split["sections"]
    assert len(secs) >= 2
    dropped, drop_focus = apply_structure_edit(
        text, split, action="drop_start", section_id=secs[1]["section_id"], language="en"
    )
    assert dropped["section_count"] == split["section_count"] - 1
    assert drop_focus == secs[0]["start_line"]
    assert coverage_report(text, dropped["sections"])["complete"] is True


def test_set_kind_and_confirm_do_not_rebuild_ids():
    text = _book()
    structure = _sections_from_boundaries(
        text,
        [
            {"start_line": 0, "kind": "front_matter", "title": "Front"},
            {"start_line": text.split("\n").index("CHAPTER I"), "kind": "chapter", "title": "CHAPTER I"},
            {"start_line": text.split("\n").index("CHAPTER II"), "kind": "chapter", "title": "CHAPTER II"},
        ],
        language="en",
    )
    ch = next(s for s in structure["sections"] if s["title"] == "CHAPTER I")
    kinded, focus = apply_structure_edit(
        text, structure, action="set_kind", section_id=ch["section_id"], kind="preface", language="en"
    )
    assert focus == ch["start_line"]
    updated = next(s for s in kinded["sections"] if s["section_id"] == ch["section_id"])
    assert updated["kind"] == "preface"
    assert updated["start_char"] == ch["start_char"]
    assert updated["end_char"] == ch["end_char"]
    assert [s["section_id"] for s in kinded["sections"]] == [s["section_id"] for s in structure["sections"]]

    confirmed, _ = apply_structure_edit(
        text, kinded, action="confirm", section_id=ch["section_id"], language="en"
    )
    assert ch["start_line"] in (confirmed.get("hitl") or {}).get("confirmed_starts")
    assert next(s for s in confirmed["sections"] if s["section_id"] == ch["section_id"])["kind"] == "preface"


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
    assert review["health"]["ready_to_parse"] is False
    assert review["health"]["can_parse"] is False
    assert "unconfirmed" in (review["health"]["not_ready_reason"] or "")


def _grotius_corpus(tmp_path, monkeypatch) -> Path:
    fixture = Path(__file__).resolve().parent / "fixtures" / "grotius_pg_snippet.txt"

    corpus = tmp_path / "corpus"
    raw_dir = corpus / "sources/grotius/raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "freedom_of_the_seas.txt").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
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
    return corpus


def _make_ready(work_id: str, corpus: Path) -> None:
    from knowledgehub.edition.read_edition_steps import confirm_toc_step, review_structure_step

    confirm_toc_step(work_id, "none", corpus=corpus)
    review = review_structure_step(work_id, corpus=corpus)
    for sid in review["health"]["untreated_flags"]:
        edit_structure_step(work_id, action="confirm", section_id=sid, corpus=corpus)


def test_set_kind_keeps_parsed_chapter_json(tmp_path, monkeypatch):
    corpus = _grotius_corpus(tmp_path, monkeypatch)
    result = run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False)
    ch_id = result["manifest"]["chapters"][0]["chapter_id"]
    parse_micro_chapter(
        "grotius--freedom_of_the_seas", ch_id, corpus=corpus, use_llm=False, require_ready=False
    )
    package_dir = corpus / result["package_dir"]
    ch_path = package_dir / "chapters" / f"{ch_id}.json"
    assert ch_path.is_file()
    before = json.loads(ch_path.read_text(encoding="utf-8"))

    edited = edit_structure_step(
        "grotius--freedom_of_the_seas",
        action="set_kind",
        section_id=ch_id,
        kind="preface",
        corpus=corpus,
    )
    assert (package_dir / "chapters" / f"{ch_id}.json").is_file()
    row = next(r for r in edited["manifest"]["chapters"] if r["chapter_id"] == ch_id)
    assert row["micro_status"] == "complete"
    assert row["kind"] == "preface"
    after = json.loads(ch_path.read_text(encoding="utf-8"))
    assert after["blocks"] == before["blocks"]
    assert after["kind"] == "preface"
    from knowledgehub.edition.read_edition_steps import load_structure

    saved = load_structure(package_dir)
    assert (saved.get("hitl") or {}).get("last_section_id") == ch_id


def test_parse_requires_hitl_ready(tmp_path, monkeypatch):
    corpus = _grotius_corpus(tmp_path, monkeypatch)
    result = run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False)
    ch_id = result["manifest"]["chapters"][0]["chapter_id"]
    with pytest.raises(ReadEditionStepError, match="not ready"):
        parse_micro_chapter("grotius--freedom_of_the_seas", ch_id, corpus=corpus, use_llm=False)
    _make_ready("grotius--freedom_of_the_seas", corpus)
    with pytest.raises(ReadEditionStepError, match="Cấu trúc OK"):
        parse_micro_chapter("grotius--freedom_of_the_seas", ch_id, corpus=corpus, use_llm=False)
    layout = confirm_layout_step("grotius--freedom_of_the_seas", corpus=corpus)
    assert layout["health"]["layout_ok"] is True
    assert layout["health"]["ready_to_parse"] is True
    assert layout["health"]["can_parse"] is True
    chapter = parse_micro_chapter("grotius--freedom_of_the_seas", ch_id, corpus=corpus, use_llm=False)
    assert chapter["micro_status"] == "complete"


def test_confirm_layout_rejected_until_ready(tmp_path, monkeypatch):
    corpus = _grotius_corpus(tmp_path, monkeypatch)
    run_macro_step("grotius--freedom_of_the_seas", corpus=corpus, use_llm=False)
    with pytest.raises(ReadEditionStepError, match="not ready"):
        confirm_layout_step("grotius--freedom_of_the_seas", corpus=corpus)


def _two_books_with_inner_toc() -> str:
    body = " ".join(["prose"] * 90)

    def one_book(label: str, chapters: tuple[str, ...]) -> str:
        toc_rows = "\n".join(f"CHAPTER {c} ........ {i}" for i, c in enumerate(chapters, 1))
        bodies = "".join(f"\nCHAPTER {c}\n\n{body}\n" for c in chapters)
        return f"BOOK {label}\n\nCONTENTS\n{toc_rows}\n{bodies}"

    return "Title page and imprint.\n\n" + one_book("I", ("I", "II")) + "\n" + one_book("II", ("III", "IV"))


def test_expand_macro_splits_super_book_into_chapters_and_toc():
    text = _two_books_with_inner_toc()
    lines = text.split("\n")
    structure = _sections_from_boundaries(
        text,
        [
            {"start_line": 0, "kind": "front_matter", "title": "Front"},
            {"start_line": lines.index("BOOK I"), "kind": "book", "title": "BOOK I"},
            {"start_line": lines.index("BOOK II"), "kind": "book", "title": "BOOK II"},
        ],
        language="en",
    )
    assert structure["section_count"] == 3
    book1 = next(s for s in structure["sections"] if s["title"] == "BOOK I")
    expanded, focus = apply_structure_edit(
        text,
        structure,
        action="expand_macro",
        section_id=book1["section_id"],
        language="en",
        use_llm=False,
    )
    assert focus == book1["start_line"]
    assert expanded["section_count"] > structure["section_count"]
    kinds = [s["kind"] for s in expanded["sections"]]
    titles = [s["title"] for s in expanded["sections"]]
    assert "toc" in kinds
    assert any("CHAPTER I" in t for t in titles)
    assert any("CHAPTER II" in t for t in titles)
    assert any(s["kind"] == "book" and s["title"] == "BOOK I" for s in expanded["sections"])
    assert any(s["kind"] == "book" and s["title"] == "BOOK II" for s in expanded["sections"])
    book1_exp = next(s for s in expanded["sections"] if s["kind"] == "book" and s["title"] == "BOOK I")
    nested = [s for s in expanded["sections"] if s.get("parent_id") == book1_exp["section_id"]]
    assert any("CHAPTER I" in s["title"] for s in nested)
    assert coverage_report(text, expanded["sections"])["complete"] is True
    for left, right in zip(expanded["sections"], expanded["sections"][1:]):
        assert int(right["start_char"]) == int(left["end_char"]) + 1


def test_heading_only_books_do_not_block_as_short():
    prose = " ".join(["word"] * 90)
    text = (
        "Title page.\n\n"
        f"BOOK I\n\nCHAPTER I\n\n{prose}\n\nCHAPTER II\n\n{prose}\n\n"
        f"BOOK II\n\nCHAPTER I\n\n{prose}\n"
    )
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=text)
    assert doc["mode"] == "markers"
    books = [s for s in doc["sections"] if s["kind"] == "book"]
    assert len(books) == 2
    review = build_review(
        text,
        {**doc, "hitl": {"toc": {"excerpt": "", "status": "none"}}},
        language="en",
    )
    by_id = {s["section_id"]: s for s in review["sections"]}
    for book in books:
        assert "short" not in (by_id[book["section_id"]].get("flags") or [])
    untreated = set(review["health"]["untreated_flags"])
    assert not {b["section_id"] for b in books} & untreated
    assert review["health"]["ready_to_parse"] is True
