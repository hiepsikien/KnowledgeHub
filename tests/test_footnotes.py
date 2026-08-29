from __future__ import annotations

from knowledgehub.edition.footnotes import (
    glossary_from_annotations,
    glossary_from_footnotes,
    notes_from_annotations,
)


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
