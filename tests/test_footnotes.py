from __future__ import annotations

from knowledgehub.edition.footnotes import (
    attach_footnote_bodies,
    glossary_from_annotations,
    glossary_from_footnotes,
    notes_from_annotations,
    notes_from_text,
)
from knowledgehub.edition.inline_spans import annotate_blocks
from knowledgehub.edition.ref import build_read_edition


def test_footnotes_become_glossary_and_leave_the_body():
    body = "CHAPTER I\n\n" + ("The argument proceeds with care. " * 40)
    raw = (
        body
        + "\nSeneca[4] thinks this is Nature's greatest service.\n\n"
        + "FOOTNOTES:\n\n"
        + "[1] Omitted section on Aristotle.\n\n"
        + "[4] Seneca, Natural Questions, book five.\n"
    )
    text, entries = glossary_from_footnotes(raw)
    assert "FOOTNOTES" not in text
    assert "Seneca[4] thinks" in text
    by_alias = {e["aliases"][0]: e for e in entries}
    assert "[4]" in by_alias
    assert by_alias["[4]"]["name"] == "Seneca [4]"
    assert by_alias["[4]"]["anchor"] == "Seneca"
    assert "Natural Questions" in by_alias["[4]"]["summary"]
    assert by_alias["[4]"]["group_label"] == "Chú thích"


def test_roman_numeral_before_marker_is_not_the_name():
    body = "CHAPTER I\n\n" + ("The argument proceeds with care. " * 40)
    raw = body + "\nIX.[1] The eighth section is omitted.\n\nFOOTNOTES:\n\n[1] Omitted.\n"
    _, entries = glossary_from_footnotes(raw)
    assert entries[0]["name"] == "[1]"
    assert entries[0]["aliases"] == ["[1]"]


def test_notes_to_essay_is_not_stripped():
    raw = (
        "CHAPTER I\n\nPainting and poetry differ in their signs.\n\n"
        "NOTES TO THE LAOCOON.\n\n"
        "[1] Pliny, Natural History, book two.\n"
    )
    text, entries = glossary_from_footnotes(raw)
    assert text == raw
    assert entries == []


def test_annotations_map_to_glossary_cards():
    rows = glossary_from_annotations(
        [
            {
                "kind": "footnote",
                "marker": "[10]",
                "anchor_text": "Victoria",
                "body_vi": "Francisco de Vitoria, trường phái Salamanca.",
            },
            {
                "kind": "glossary",
                "anchor_text": "Luật các dân tộc",
                "body_vi": "Jus gentium.",
            },
        ]
    )
    assert rows[0]["name"] == "Victoria [10]"
    assert rows[0]["aliases"] == ["[10]"]
    assert rows[0]["marker"] == "[10]"
    assert rows[1]["group_label"] == "Thuật ngữ"


def test_notes_dedupe_glossary_and_unique_footnote_labels():
    notes = notes_from_annotations(
        [
            {
                "id": "a",
                "kind": "glossary",
                "chapter": "I",
                "anchor_text": "Luật các dân tộc",
                "title_vi": "Luật các dân tộc",
                "body_vi": "Jus gentium — bản I.",
            },
            {
                "id": "b",
                "kind": "glossary",
                "chapter": "V",
                "anchor_text": "Luật các dân tộc",
                "title_vi": "Luật các dân tộc (Jus Gentium)",
                "body_vi": "Jus gentium — bản V.",
            },
            {
                "id": "c",
                "kind": "footnote",
                "chapter": "I",
                "marker": "[4]",
                "anchor_text": "Seneca",
                "title_vi": "Chú thích [4]",
                "body_vi": "Seneca trẻ.",
            },
            {
                "id": "d",
                "kind": "footnote",
                "chapter": "V",
                "marker": "[48]",
                "anchor_text": "Seneca",
                "title_vi": "Chú thích [48]",
                "body_vi": "Seneca, Thyestes.",
            },
        ]
    )
    labels = [row["label"] for row in notes]
    assert labels.count("Luật các dân tộc") == 1
    assert "Seneca [4]" in labels
    assert "Seneca [48]" in labels
    seneca_four = next(row for row in notes if row["marker"] == "[4]")
    assert seneca_four["aliases"] == ["[4]"]


def test_notes_drop_context_that_restates_a_footnote():
    items = [
        {
            "id": "fn-12",
            "kind": "footnote",
            "chapter": "I",
            "marker": "[12]",
            "anchor_text": "Augustine",
            "title_vi": "Augustine [12]",
            "body_vi": "Ông lập luận rằng việc từ chối một lối đi vô hại là lý do chính đáng để tiến hành chiến tranh.",
        },
        {
            "id": "ctx-passage",
            "kind": "context",
            "chapter": "I",
            "anchor_text": "lối đi vô hại",
            "title_vi": "Bối cảnh pháp lý",
            "body_vi": "Khái niệm transitus innoxius.",
        },
        {
            "id": "ctx-vasquez",
            "kind": "context",
            "chapter": "I",
            "anchor_text": "Vasquez",
            "title_vi": "Bối cảnh lịch sử",
            "body_vi": "Fernando Vázquez de Menchaca, Trường phái Salamanca.",
        },
        {
            "id": "fn-171",
            "kind": "footnote",
            "chapter": "I",
            "marker": "[171]",
            "anchor_text": "độc quyền",
            "title_vi": "Chú thích [171]",
            "body_vi": "Lập luận về độc quyền thương mại giữa các nước.",
        },
        {
            "id": "gloss-law",
            "kind": "glossary",
            "chapter": "I",
            "anchor_text": "Luật các dân tộc",
            "title_vi": "Luật các dân tộc",
            "body_vi": "Jus gentium.",
        },
    ]
    chapter = (
        "Chúng ta đọc thấy trong các tác phẩm của Augustine,[12] "
        "khi người Israel bị khước từ lối đi vô hại qua lãnh thổ. "
        "Vasquez bác bỏ độc quyền.[171] "
        "Theo Luật các dân tộc thì biển là của chung."
    )
    notes = notes_from_annotations(items, chapter_texts={"I": chapter})
    labels = [row["label"] for row in notes]
    assert "Augustine [12]" in labels
    assert "lối đi vô hại" not in labels
    assert "Bối cảnh pháp lý" not in labels
    assert any("Vasquez" in row["label"] or row["anchor"] == "Vasquez" for row in notes)
    assert "Luật các dân tộc" in labels


BERGSON_CHAPTER = """\
CHAPTER I

THE EVOLUTION OF LIFE

True, biologists are not agreed on what is gained and what is lost
between the day of birth and the day of death.[5] More probable is the
theory of residual substances which finally "crust it over."[6] Must we
declare any explanation insufficient that does not take account of
phagocytosis?[7]

FOOTNOTES:

[Footnote 5: There are those who hold to the continual growth in the
volume of protoplasm from the birth of the cell right on to its death.]

[Footnote 6: Le Dantec, _L'Individualité et l'erreur individualiste_,
Paris, 1905, pp. 84 ff.]

[Footnote 7: Metchnikoff, _La Dégénérescence sénile_.]
"""

BACH_CHAPTER = """\
CHAPTER I

HIS CHILDREN

Johann Sebastian had a second son.[1] The violas were divided.[2]
Spitta records the visit.[5]

FOOTNOTES:

[1] See Glossary, "College of Instrumental Musicians."

[2] The violas were divided into alto, tenor and bass, as the trombones
are now.

[5] Spitta.
"""


def test_per_chapter_numbered_notes_are_extracted():
    body, entries = glossary_from_footnotes(BACH_CHAPTER)
    assert "FOOTNOTES" not in body
    assert "Johann Sebastian had a second son.[1]" in body
    by_alias = {e["aliases"][0]: e for e in entries}
    assert by_alias["[1]"]["summary"].startswith("See Glossary")
    assert by_alias["[5]"]["summary"] == "Spitta."


def test_per_chapter_gutenberg_bracket_notes_are_extracted():
    parsed = notes_from_text(BERGSON_CHAPTER)
    assert 5 in parsed
    assert "volume of protoplasm" in parsed[5]
    assert "Le Dantec" in parsed[6]
    assert parsed[7].startswith("Metchnikoff")
    body, entries = glossary_from_footnotes(BERGSON_CHAPTER)
    assert "FOOTNOTES" not in body
    assert "phagocytosis?[7]" in body
    assert any("Matière" in e["summary"] or "Le Dantec" in e["summary"] for e in entries)


def test_multiple_chapter_footnote_dumps():
    raw = BACH_CHAPTER + "\n\nCHAPTER II\n\nLater years.[7]\n\nFOOTNOTES:\n\n[7] No. 27 in the Genealogical List.\n"
    body, entries = glossary_from_footnotes(raw)
    assert "CHAPTER II" in body
    assert "Later years.[7]" in body
    assert "FOOTNOTES" not in body
    markers = {e["aliases"][0] for e in entries}
    assert markers == {"[1]", "[2]", "[5]", "[7]"}


def test_mixed_case_chapter_stops_the_dump():
    raw = (
        "Chapter I\n\nHis children.[1]\n\nFOOTNOTES:\n\n[1] See Glossary.\n\n"
        "Chapter II\n\nLater years continue here.\n"
    )
    body, entries = glossary_from_footnotes(raw)
    assert "Chapter II" in body
    assert "Later years continue here" in body
    assert "FOOTNOTES" not in body
    assert entries[0]["summary"].startswith("See Glossary")


def test_ref_attaches_bergson_note_bodies_to_markers():
    edition, report = build_read_edition(BERGSON_CHAPTER, family="gutenberg", language="en", use_llm=False)
    assert report["notes_linked"] >= 3
    notes = {row["marker"]: row["body"] for row in edition.get("notes") or []}
    assert "volume of protoplasm" in notes["[5]"]
    linked = [
        span
        for block in edition["blocks"]
        for span in block.get("spans") or []
        if span.get("style") == "footnote" and span.get("text") == "[5]" and span.get("note")
    ]
    assert linked
    assert "volume of protoplasm" in linked[0]["note"]


def test_ref_attaches_abdy_williams_note_bodies_to_markers():
    edition, report = build_read_edition(BACH_CHAPTER, family="gutenberg", language="en", use_llm=False)
    assert report["notes_linked"] >= 3
    notes = {row["marker"]: row["body"] for row in edition.get("notes") or []}
    assert notes["[1]"].startswith("See Glossary")
    assert notes["[5]"] == "Spitta."
    five = [
        span
        for block in edition["blocks"]
        for span in block.get("spans") or []
        if span.get("style") == "footnote" and span.get("text") == "[5]"
    ]
    assert five and five[0].get("note") == "Spitta."


def test_attach_footnote_bodies_on_annotated_blocks():
    blocks = [
        {"type": "paragraph", "text": "The violas were divided.[2]"},
        {"type": "heading", "level": 2, "text": "FOOTNOTES:"},
        {"type": "paragraph", "text": "[2] The violas were divided into alto, tenor and bass."},
    ]
    annotated, _ = annotate_blocks(blocks)
    out, notes = attach_footnote_bodies(annotated, BACH_CHAPTER)
    span = next(s for s in out[0]["spans"] if s["style"] == "footnote")
    assert span["note"].startswith("The violas were divided into alto")
    assert any(row["marker"] == "[2]" for row in notes)

