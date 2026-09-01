from __future__ import annotations

from pathlib import Path

import pytest

from knowledgehub.edition.detect import _heading_key, _toc_title_repeats
from knowledgehub.edition.macro import build_macro_structure, scan_heading_candidates
from knowledgehub.edition.macro_markers import resolve_division_level, try_marker_assembly
from knowledgehub.edition.macro_qa import detect_body_markers, extract_title_page_toc, extract_toc_from_raw, parse_title_page_entries
from knowledgehub.edition.pipeline import build_edition
from knowledgehub.edition.toc import (
    chapter_number_key,
    heading_title_from_toc_match,
    is_body_heading_line,
    is_chapter_number_only_line,
    is_toc_list_row,
    parse_contents_entries,
    toc_is_heading_list_map,
    toc_is_page_column_map,
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
    assert "CHAPTER XIV" in excerpt


def test_extract_toc_preserves_compact_list_newlines():
    raw = """Title

CONTENTS

Preface: iii-lx
I: 1-50 (Sweetness and Light)
II: 51-92 (Doing as One Likes)
VI: 197-272 (Our Liberal Practitioners)

*Note: in the first edition, chapters are numbered only, not named.

CULTURE AND ANARCHY (1869, FIRST EDITION)

PREFACE

[iii] My foremost design in writing this Preface is to address a word
of exhortation to the Society.
"""
    excerpt = extract_toc_from_raw(raw)
    assert "Preface: iii-lx\nI: 1-50 (Sweetness and Light)\nII: 51-92" in excerpt
    assert "foremost design" not in excerpt
    assert excerpt.count("\n") >= 4


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
    assert "toc" not in kinds


def test_empty_toc_excerpt_skips_auto_toc_match():
    raw, text = _abdy_toc_and_body()
    auto = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert auto["mode"] == "toc_match"
    skipped = build_macro_structure(
        text, language="en", family="gutenberg", use_llm=False, raw=raw, toc_excerpt=""
    )
    assert skipped["mode"] != "toc_match"


def test_curated_wrap_excerpt_drives_toc_match_over_junk_raw():
    raw, text = _abdy_toc_and_body()
    junk = """Title page

CONTENTS

Wrong leftover essay  1
Another leftover title  2

""" + text
    auto = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=junk)
    assert auto["mode"] != "toc_match" or "Chapter I" not in [s["title"] for s in auto["sections"]]
    curated = """CONTENTS

                                                                     PAGE

 PREFACE                                                                v


 CHAPTER I

 The Bachs of Thuringia                                                 1


 CHAPTER II

 Bach’s attitude towards art                                           20
"""
    doc = build_macro_structure(
        text, language="en", family="gutenberg", use_llm=False, raw=junk, toc_excerpt=curated
    )
    assert doc["mode"] == "toc_match"
    titles = [s["title"] for s in doc["sections"]]
    kinds = [s["kind"] for s in doc["sections"]]
    assert "preface" in kinds
    assert kinds.count("chapter") == 2
    assert any("Chapter I" in t for t in titles)
    assert any("Chapter II" in t for t in titles)
    assert not any("leftover" in t.lower() for t in titles)


def test_macro_abdy_williams_full_pg():
    raw_path = Path("/tmp/pg_full/pg43650.txt")
    if not raw_path.is_file():
        pytest.skip("PG cache missing — compact fixtures cover Abdy wrap TOC")
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
        pytest.skip("PG cache missing — compact Austen TOC fixture covers markers")
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
        pytest.skip("PG cache missing — compact Austen TOC fixture covers markers")
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
    assert not toc_is_page_column_map(entries)


def test_macro_keeps_markers_for_austen_style_one_line_toc():
    text = _austen_style_one_line_toc()
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=text)
    assert doc["mode"] == "markers"
    kinds = [s["kind"] for s in doc["sections"]]
    assert kinds.count("chapter") == 5
    assert not any(s.get("parent_id") for s in doc["sections"] if s["kind"] == "chapter")


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


def test_unmatched_back_matter_still_allows_toc_match():
    raw = """Title

Contents


                                                                     PAGE

 CHAPTER I

 The Bachs of Thuringia--Veit Bach                                     1


 CHAPTER II

 Bach’s attitude towards art                                           20


 CATALOGUE OF VOCAL WORKS                                             177

 GLOSSARY                                                             205


Chapter I

John Sebastian Bach came of a large family.

Chapter II

He was born at Eisenach. Matthew Passion is listed only here; Ahle, Joh. Rudolph.
"""
    entries = parse_contents_entries(raw)
    kinds = [e["kind"] for e in entries]
    assert kinds.count("chapter") == 2
    assert kinds.count("back_matter") == 2
    matched = match_toc_entries_in_body(raw, entries)
    assert toc_is_wrap_page_column(entries)
    assert toc_match_covers_structure(entries, matched)
    assert len(matched) == 2
    doc = build_macro_structure(raw, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] == "toc_match"
    section_kinds = [s["kind"] for s in doc["sections"]]
    assert "toc" not in section_kinds
    assert section_kinds.count("back_matter") == 0
    last = doc["sections"][-1]
    assert last["kind"] == "chapter"
    slice_text = raw[int(last["start_char"]) : int(last["end_char"]) + 1]
    assert "Matthew Passion" in slice_text
    assert "Ahle" in slice_text


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


def _arnold_named_page_column_toc() -> str:
    """Matthew Arnold, Discourses in America — named essays + page column, split first heading."""
    return """*** START OF THE PROJECT GUTENBERG EBOOK DISCOURSES IN AMERICA ***

DISCOURSES IN AMERICA

BY
MATTHEW ARNOLD

PREFACE.

Of the three discourses in this volume, the second was originally given
as the Rede Lecture at Cambridge.

CONTENTS.


                                                      PAGE

  Numbers; or, The Majority and the Remnant              1

  Literature and Science                                72

  Emerson                                              138



  NUMBERS;
  OR,
  THE MAJORITY AND THE REMNANT.


There is a characteristic saying of Dr. Johnson: Patriotism is the last
refuge of a scoundrel. The saying is cynical yet it has in it something
of plain robust sense and truth, and we do often see men passing
themselves off as patriots who are in truth scoundrels of the common
sort. Short of such, there is undoubtedly a good deal of self-flattery.

  LITERATURE AND SCIENCE.


The question of public education is a question of high importance in
modern life, and it is a question on which the public is not agreed at
present. Literature and science both claim a place.

  EMERSON.


Towards Emerson the feelings of his countrymen have not always been
steady, but they have been strong, and they remain a living force.

*** END OF THE PROJECT GUTENBERG EBOOK DISCOURSES IN AMERICA ***
"""


def test_named_page_column_toc_is_a_map():
    entries = parse_contents_entries(_arnold_named_page_column_toc())
    labels = [e["label"] for e in entries]
    assert labels == [
        "Numbers; or, The Majority and the Remnant",
        "Literature and Science",
        "Emerson",
    ]
    assert all(e["kind"] == "other" for e in entries)
    assert not toc_is_wrap_page_column(entries)
    assert toc_is_page_column_map(entries)


def test_macro_uses_toc_for_arnold_named_essays():
    raw = _arnold_named_page_column_toc()
    entries = parse_contents_entries(raw)
    matched = match_toc_entries_in_body(raw, entries)
    assert [m["label"] for m in matched] == [e["label"] for e in entries]
    assert "NUMBERS;" in matched[0]["text"]
    assert "MAJORITY" in matched[0]["text"].upper()
    assert toc_match_covers_structure(entries, matched)
    doc = build_macro_structure(raw, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] == "toc_match"
    kinds = [s["kind"] for s in doc["sections"]]
    titles = [s["title"] for s in doc["sections"]]
    assert kinds[0] == "front_matter"
    assert kinds.count("chapter") == 3
    assert any("NUMBERS;" in t and "MAJORITY" in t.upper() for t in titles)
    assert any("LITERATURE AND SCIENCE" in t for t in titles)
    assert any("EMERSON" in t for t in titles)


def test_strip_keeps_arnold_first_essay_heading():
    raw = _arnold_named_page_column_toc()
    text, report = build_edition(raw, language="en", strip_only=True)
    assert report["dropped_contents"] is True
    assert "Numbers; or, The Majority and the Remnant" not in text
    assert "NUMBERS;" in text
    assert "THE MAJORITY AND THE REMNANT." in text
    assert "LITERATURE AND SCIENCE." in text
    assert "EMERSON." in text
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] == "toc_match"
    assert [s["kind"] for s in doc["sections"]].count("chapter") == 3


def _arnold_essays_page_column_toc() -> str:
    """Essays in Criticism (PG 77244): TOC I–XIX vs body reprint I. / IX. for series 2."""
    return """*** START OF THE PROJECT GUTENBERG EBOOK ESSAYS IN CRITICISM ***

ESSAYS IN CRITICISM

CONTENTS.

  CHAPTER                                                           PAGE

       I. THE FUNCTION OF CRITICISM AT THE PRESENT TIME                1

      XI. THE STUDY OF POETRY                                        279

     XII. MILTON                                                     308

    XIII. THOMAS GRAY                                                315

     XIX. AMIEL                                                      432



                          ESSAYS IN CRITICISM.

                             --------------

                                   I.
                THE FUNCTION OF CRITICISM AT THE PRESENT
                                 TIME.

Many objections have been made to a proposition which, in some remarks
of mine on translating Homer, I ventured to put forth; a proposition
about criticism, and its importance at the present day.

                                   I.

                        THE STUDY OF POETRY.

The future of poetry is immense, because in poetry, where it is worthy
of its high destinies, our race will find an ever surer stay.

                                  XII.

                               MILTON

The most eloquent voice of our century uttered, shortly before leaving
the world, a warning cry against the Anglo-Saxon contagion.

                                  III.

                              THOMAS GRAY.

James Brown, Master of Pembroke Hall at Cambridge, Gray’s friend and
executor, wrote a letter a fortnight after Gray’s death.

                                  IX.

                               AMIEL.

It is somewhat late to speak of Amiel, but I was late in reading him.
Goethe says that in seasons of cholera one should read no books but
such as are tonic.

*** END OF THE PROJECT GUTENBERG EBOOK ESSAYS IN CRITICISM ***
"""


def test_parse_arnold_essays_consecutive_toc():
    entries = parse_contents_entries(_arnold_essays_page_column_toc())
    labels = [e["label"] for e in entries]
    assert labels[0] == "I. THE FUNCTION OF CRITICISM AT THE PRESENT TIME"
    assert "XI. THE STUDY OF POETRY" in labels
    assert "XIX. AMIEL" in labels
    assert toc_is_page_column_map(entries)


def test_strip_keeps_arnold_essays_first_heading():
    raw = _arnold_essays_page_column_toc()
    text, report = build_edition(raw, language="en", strip_only=True)
    assert report["dropped_contents"] is True
    assert "XI. THE STUDY OF POETRY                                        279" not in text
    assert "THE FUNCTION OF CRITICISM AT THE PRESENT" in text
    assert "Many objections have been made" in text


def test_macro_uses_toc_numbers_not_body_reprint():
    raw = _arnold_essays_page_column_toc()
    text, _ = build_edition(raw, language="en", strip_only=True)
    entries = parse_contents_entries(raw)
    matched = match_toc_entries_in_body(text, entries)
    assert toc_match_covers_structure(entries, matched)
    assert [m["label"] for m in matched] == [e["label"] for e in entries]
    lines = text.splitlines()
    first = matched[0]
    assert is_chapter_number_only_line(lines[first["line"]].strip())
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] == "toc_match"
    titles = [s["title"] for s in doc["sections"] if s["kind"] == "chapter"]
    assert titles[0].startswith("I. THE FUNCTION OF CRITICISM")
    assert any(t.startswith("XI. THE STUDY OF POETRY") for t in titles)
    assert any(t.startswith("XII. MILTON") for t in titles)
    assert any(t.startswith("XIII. THOMAS GRAY") for t in titles)
    assert any(t.startswith("XIX. AMIEL") for t in titles)
    assert not any(t.startswith("IX. AMIEL") for t in titles)
    assert sum(1 for t in titles if t.startswith("I.") and "STUDY OF POETRY" in t.upper()) == 0


def test_roman_numeral_not_glued_to_following_prose():
    """Lone ``I.`` plus a prose paragraph is not a chapter title."""
    from knowledgehub.edition.toc import _attach_leading_chapter_number

    lines = ["I.", "", "Many objections have been made to a proposition which, in some remarks"]
    assert is_chapter_number_only_line(lines[0])
    assert _attach_leading_chapter_number(lines, 2) == 2


def test_heading_title_prefers_toc_ordinal_and_strips_footnote():
    assert heading_title_from_toc_match(
        {"label": "XI. THE STUDY OF POETRY", "text": "I. THE STUDY OF POETRY"}
    ) == "XI. THE STUDY OF POETRY"
    assert heading_title_from_toc_match(
        {"label": "XII. MILTON", "text": "XII. MILTON[34]"}
    ) == "XII. MILTON"


def test_title_key_folds_accents():
    from knowledgehub.edition.toc import _title_key

    assert _title_key("III. MAURICE DE GUERIN") == _title_key("MAURICE DE GUÉRIN.")


def test_toc_match_cursor_does_not_rescan_current_title():
    """Longer title must not be reused as a token-subset hit for the next TOC row."""
    raw = """*** START OF THE PROJECT GUTENBERG EBOOK DEMO ***

CONTENTS.

       I. THE STUDY OF POETRY AND LIFE              1

      II. THE STUDY OF POETRY                      10



                                   I.

                        THE STUDY OF POETRY AND LIFE.

The first essay discusses poetry as it bears on life at some length here.

                                  II.

                        THE STUDY OF POETRY.

The second essay is only about poetry as such, without the life theme.

*** END OF THE PROJECT GUTENBERG EBOOK DEMO ***
"""
    entries = parse_contents_entries(raw)
    assert [e["label"] for e in entries] == [
        "I. THE STUDY OF POETRY AND LIFE",
        "II. THE STUDY OF POETRY",
    ]
    text, _ = build_edition(raw, language="en", strip_only=True)
    matched = match_toc_entries_in_body(text, entries)
    assert [m["label"] for m in matched] == [e["label"] for e in entries]
    lines = text.splitlines()
    assert "AND LIFE" in lines[matched[0]["line"] + 1].upper() or "AND LIFE" in (
        matched[0].get("text") or ""
    ).upper()
    assert "AND LIFE" not in (matched[1].get("text") or "").upper()
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=raw)
    titles = [s["title"] for s in doc["sections"] if s["kind"] == "chapter"]
    assert titles[0].startswith("I. THE STUDY OF POETRY AND LIFE")
    assert titles[1].startswith("II. THE STUDY OF POETRY")
    assert "AND LIFE" not in titles[1].upper()


def test_toc_title_repeats_prefix_not_first_word():
    seen = {
        _heading_key("CHAPTER I.     Mr. Bennet sees Bingley          1"),
        _heading_key("CHAPTER II.    Visit to Netherfield             8"),
        _heading_key("CHAPTER III.   The assembly                    15"),
    }
    assert not _toc_title_repeats(_heading_key("CHAPTER IV.    Jane's letter                   22"), seen)
    assert _toc_title_repeats(_heading_key("Chapter 1"), seen)
    arnold_toc = _heading_key("Numbers; or, The Majority and the Remnant              1")
    assert _toc_title_repeats(_heading_key("NUMBERS;"), {arnold_toc})
    function_toc = _heading_key("I. THE FUNCTION OF CRITICISM AT THE PRESENT TIME                1")
    assert _toc_title_repeats(
        _heading_key("THE FUNCTION OF CRITICISM AT THE PRESENT"), {function_toc}
    )
    volume_seen = {
        _heading_key("VOLUME I. First                     1"),
        _heading_key("VOLUME II. Second                    2"),
        _heading_key("VOLUME III. Third                    3"),
    }
    assert not _toc_title_repeats(_heading_key("VOLUME IV. Fourth                    4"), volume_seen)
    assert _toc_title_repeats(_heading_key("VOLUME I"), volume_seen)


def _chapter_i_to_v_contents() -> str:
    return """*** START OF THE PROJECT GUTENBERG EBOOK PRIDE AND PREJUDICE ***

Title page

CONTENTS

CHAPTER I.     Mr. Bennet sees Bingley          1
CHAPTER II.    Visit to Netherfield             8
CHAPTER III.   The assembly                    15
CHAPTER IV.    Jane's letter                   22
CHAPTER V.     The ball                        30

Chapter 1

It is a truth universally acknowledged that a single man in possession
of a good fortune must be in want of a wife.

Chapter 2

Mr. Bennet was among the earliest of those who waited on Mr. Bingley.

Chapter 3

Not all that Mrs. Bennet, however, with the assistance of her five daughters.

Chapter 4

When Jane and Elizabeth were alone, Jane told her sister the letter.

Chapter 5

The village of Longbourn was only one mile from Meryton.

*** END OF THE PROJECT GUTENBERG EBOOK PRIDE AND PREJUDICE ***
"""


def test_chapter_i_to_v_contents_is_stripped_not_cut_at_iv():
    raw = _chapter_i_to_v_contents()
    text, report = build_edition(raw, language="en", strip_only=True)
    assert report["dropped_contents"] is True
    assert "Jane's letter" not in text
    assert "Mr. Bennet sees Bingley" not in text
    assert "It is a truth universally acknowledged" in text
    assert "When Jane and Elizabeth were alone" in text
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] == "markers"
    assert [s["kind"] for s in doc["sections"]].count("chapter") == 5


def test_dedication_in_named_toc_is_not_required():
    raw = """*** START OF THE PROJECT GUTENBERG EBOOK DISCOURSES IN AMERICA ***

CONTENTS.


                                                      PAGE

  Dedication                                           vii

  To the Reader                                        xii

  Numbers; or, The Majority and the Remnant              1

  Literature and Science                                72

  Emerson                                              138



  NUMBERS;
  OR,
  THE MAJORITY AND THE REMNANT.


There is a characteristic saying of Dr. Johnson: Patriotism is the last
refuge of a scoundrel. The saying is cynical yet it has in it something
of plain robust sense and truth.

  LITERATURE AND SCIENCE.


The question of public education is a question of high importance in
modern life, and it is a question on which the public is not agreed.

  EMERSON.


Towards Emerson the feelings of his countrymen have not always been
steady, but they have been strong.

*** END OF THE PROJECT GUTENBERG EBOOK DISCOURSES IN AMERICA ***
"""
    entries = parse_contents_entries(raw)
    labels = [e["label"] for e in entries]
    assert any(lab.lower().startswith("dedication") for lab in labels)
    assert any("reader" in lab.lower() for lab in labels)
    assert all(e["kind"] == "other" for e in entries)
    matched = match_toc_entries_in_body(raw, entries)
    assert toc_match_covers_structure(entries, matched)
    assert [m["label"] for m in matched] == [
        "Numbers; or, The Majority and the Remnant",
        "Literature and Science",
        "Emerson",
    ]
    doc = build_macro_structure(raw, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] == "toc_match"
    assert [s["kind"] for s in doc["sections"]].count("chapter") == 3


def test_pg_arnold_discourses_if_cached():
    raw_path = Path("/tmp/pg44919.txt")
    if not raw_path.is_file():
        pytest.skip("PG 44919 cache missing — compact Arnold fixture covers named TOC")
    raw = raw_path.read_text(encoding="utf-8", errors="replace")
    text, report = build_edition(raw, language="en", strip_only=True)
    assert report["dropped_contents"] is True
    assert "NUMBERS;" in text
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=raw)
    assert doc["mode"] == "toc_match"
    titles = [s["title"] for s in doc["sections"]]
    assert any("NUMBERS" in t for t in titles)
    assert any("LITERATURE AND SCIENCE" in t for t in titles)
    assert any("EMERSON" in t for t in titles)
    assert [s["kind"] for s in doc["sections"]].count("chapter") == 3


def test_build_macro_structure_markers_path_grotius():
    raw_path = Path("/tmp/pg_full/pg75962.txt")
    if not raw_path.is_file():
        pytest.skip("PG cache missing — Grotius snippet tests cover markers/HITL")
    text, _ = build_edition(raw_path.read_text(encoding="utf-8"), language="en", strip_only=True)
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False)
    assert doc["mode"] == "markers"
    assert [s["kind"] for s in doc["sections"]].count("chapter") >= 10


def _politics_nested_books() -> str:
    prose = " ".join(["word"] * 90)
    chunks = [
        "Title page and translator note.\n\n",
        "INTRODUCTION\n\n",
        f"The Politics of Aristotle looks back to the Ethics. {prose}\n\n",
    ]
    for book in ("I", "II"):
        chunks.append(f"BOOK {book}\n\n")
        for chapter in ("I", "II", "III"):
            chunks.append(
                f"CHAPTER {chapter}\n\nAs we see that every city is a society. {prose}\n\n"
            )
    return "".join(chunks)


def test_nested_books_and_chapters_politics_shape():
    text = _politics_nested_books()
    markers = detect_body_markers(text)
    assert resolve_division_level(markers) == "chapter"
    assert sum(1 for m in markers if m["kind"] == "book") == 2
    assert sum(1 for m in markers if m["kind"] == "chapter") == 6

    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=text)
    assert doc["mode"] == "markers"
    kinds = [s["kind"] for s in doc["sections"]]
    assert kinds.count("book") == 2
    assert kinds.count("chapter") >= 6

    books = [s for s in doc["sections"] if s["kind"] == "book"]
    assert books[0]["title"].startswith("BOOK I")
    assert books[1]["title"].startswith("BOOK II")
    book_slice = text[books[0]["start_char"] : books[0]["end_char"] + 1]
    assert "BOOK I" in book_slice
    assert "CHAPTER I" not in book_slice

    nested = [s for s in doc["sections"] if s.get("parent_id") == books[0]["section_id"]]
    assert [s["title"] for s in nested] == ["CHAPTER I", "CHAPTER II", "CHAPTER III"]
    ch1 = nested[0]
    ch_slice = text[ch1["start_char"] : ch1["end_char"] + 1].lstrip()
    assert ch_slice.startswith("CHAPTER I")
    assert "BOOK I" not in ch_slice

    book2_children = [s for s in doc["sections"] if s.get("parent_id") == books[1]["section_id"]]
    assert len(book2_children) == 3
    assert all(c["kind"] == "chapter" for c in book2_children)

    for left, right in zip(doc["sections"], doc["sections"][1:]):
        assert int(right["start_char"]) == int(left["end_char"]) + 1


def test_nested_part_inside_book():
    prose = " ".join(["word"] * 90)
    text = (
        "Front matter note.\n\n"
        f"BOOK I\n\nPART I\n\nCHAPTER I\n\n{prose}\n\nCHAPTER II\n\n{prose}\n\n"
        f"BOOK II\n\nCHAPTER I\n\n{prose}\n"
    )
    doc = build_macro_structure(text, language="en", family="gutenberg", use_llm=False, raw=text)
    assert doc["mode"] == "markers"
    books = [s for s in doc["sections"] if s["kind"] == "book"]
    parts = [s for s in doc["sections"] if s["kind"] == "part"]
    assert len(books) == 2
    assert len(parts) == 1
    assert parts[0]["parent_id"] == books[0]["section_id"]
    under_part = [s for s in doc["sections"] if s.get("parent_id") == parts[0]["section_id"]]
    assert [s["title"] for s in under_part] == ["CHAPTER I", "CHAPTER II"]
    under_book2 = [s for s in doc["sections"] if s.get("parent_id") == books[1]["section_id"]]
    assert len(under_book2) == 1
    assert under_book2[0]["title"].startswith("CHAPTER I")


_HEGEL_TOC = """CONTENTS


Preface.
Five Introductory Essays In Psychology And Ethics.
   Essay I. On The Scope Of A Philosophy Of Mind.
   Essay II. Aims And Methods Of Psychology.
   Essay III. On Some Psychological Aspects Of Ethics.
   Essay IV. Psycho-Genesis.
   Essay V. Ethics And Politics.
Introduction.
Section I. Mind Subjective.
   Sub-Section A. Anthropology. The Soul.
   Sub-Section B. Phenomenology Of Mind. Consciousness.
   Sub-Section C. Psychology. Mind.
Section II. Mind Objective.
   Distribution.
   Sub-Section A. Law.
   Sub-Section B. The Morality Of Conscience.
   Sub-Section C. The Moral Life, Or Social Ethics.
Section III. Absolute Mind.
   Sub-Section A. Art.
   Sub-Section B. Revealed Religion.
   Sub-Section C. Philosophy.
Index.
Footnotes
"""


def _hegel_body() -> str:
    prose = " ".join(["word"] * 40)
    return f"""THE PHILOSOPHY OF MIND

{prose}

Preface.

{prose}

Five Introductory Essays In Psychology And Ethics.

Essay I. On The Scope Of A Philosophy Of Mind.

{prose}

Essay II. Aims And Methods Of Psychology.

{prose}

Essay III. On Some Psychological Aspects Of Ethics.

{prose}

Essay IV. Psycho-Genesis.

{prose}

Essay V. Ethics And Politics.

{prose}

Introduction.

{prose}

Section I. Mind Subjective.

Sub-Section A. Anthropology. The Soul.

{prose}

Sub-Section B. Phenomenology Of Mind. Consciousness.

{prose}

Sub-Section C. Psychology. Mind.

{prose}

Section II. Mind Objective.

Distribution.

{prose}

Sub-Section A. Law.

{prose}

Sub-Section B. The Morality Of Conscience.

{prose}

Sub-Section C. The Moral Life, Or Social Ethics.

{prose}

Section III. Absolute Mind.

Sub-Section A. Art.

{prose}

Sub-Section B. Revealed Religion.

{prose}

Sub-Section C. Philosophy.

{prose}

Index.

{prose}

Footnotes

{prose}
"""


def test_hegel_title_list_toc_parses_essays_and_sections():
    entries = parse_contents_entries(_HEGEL_TOC)
    labels = [e["label"] for e in entries]
    kinds = [e["kind"] for e in entries]
    assert "Preface" in labels[0]
    assert any("Five Introductory Essays" in lab for lab in labels)
    assert any("Essay I." in lab and "Scope" in lab for lab in labels)
    assert any("Essay V." in lab for lab in labels)
    assert any(lab.startswith("Introduction") for lab in labels)
    assert any("Section I." in lab and "Mind Subjective" in lab for lab in labels)
    assert any("Sub-Section A." in lab and "Anthropology" in lab for lab in labels)
    assert any("Law" in lab and "Sub-Section A" in lab for lab in labels)
    assert any("Distribution" in lab for lab in labels)
    assert any("Section III." in lab for lab in labels)
    assert any("Philosophy" in lab for lab in labels)
    assert any(lab.upper().startswith("INDEX") for lab in labels)
    assert any("FOOTNOTE" in lab.upper() for lab in labels)
    assert kinds.count("chapter") == 14  # 5 essays + 9 sub-sections
    assert kinds.count("part") == 3
    assert kinds.count("preface") == 1
    assert kinds.count("introduction") == 1
    assert not any(e.get("page") for e in entries)
    assert toc_is_heading_list_map(entries)
    assert not toc_is_page_column_map(entries)
    # Must not wrap the whole book into Preface / Introduction.
    preface = next(e for e in entries if e["kind"] == "preface")
    assert "Essay" not in (preface.get("title") or "")
    intro = next(e for e in entries if e["kind"] == "introduction")
    assert "Section" not in (intro.get("title") or "")


def test_hegel_title_list_toc_match_splits_body():
    text = _hegel_body()
    entries = parse_contents_entries(_HEGEL_TOC)
    matched = match_toc_entries_in_body(text, entries)
    assert toc_match_covers_structure(entries, matched)
    doc = build_macro_structure(
        text, language="en", family="gutenberg", use_llm=False, toc_excerpt=_HEGEL_TOC
    )
    assert doc["mode"] == "toc_match"
    titles = [s["title"] for s in doc["sections"]]
    kinds = [s["kind"] for s in doc["sections"]]
    assert any("Essay I" in t and "Scope" in t for t in titles)
    assert any("Essay V" in t for t in titles)
    assert any("Section I" in t and "Mind Subjective" in t for t in titles)
    assert any("Anthropology" in t for t in titles)
    assert any("Sub-Section A. Law" in t or t.endswith("Law") or t.endswith("Law.") for t in titles)
    assert any("Philosophy" in t and "Sub-Section" in t for t in titles)
    assert "preface" in kinds
    assert "introduction" in kinds
    assert kinds.count("part") == 3
    assert kinds.count("chapter") >= 14


def test_body_heading_recognizes_essay_and_subsection():
    assert is_body_heading_line("Essay I. On The Scope Of A Philosophy Of Mind.")
    assert is_body_heading_line("Section I. Mind Subjective.")
    assert is_body_heading_line("Sub-Section A. Anthropology. The Soul.")
    assert not is_toc_list_row("Essay I. On The Scope Of A Philosophy Of Mind.")
