from __future__ import annotations

from pathlib import Path

from knowledgehub.edition.glossary import (
    attach_book_glossary,
    expand_see_glossary_body,
    parse_glossary_entries,
)
from knowledgehub.read_publish import _attach_edition

BACH_GLOSSARY = """\
Glossary

~Ahle~, Joh. Rudolph, was born 1625, and, after holding a post at
Erfurt, became organist and burgomaster of his native town Mühlhausen.

~Böhm~, Georg. Is described by Walther as a fine composer and
organist of St John at Lüneburg.

~Cembalo~, or clavicymbal, or clavessin, or clavecin, for which Bach
wrote his clavier works, was in shape like the modern grand piano.

~Clavicymbal.~ See Cembalo.

~College~ of Instrumental Musicians of Upper and Lower Saxony. The full
text is given by Spitta, vol. i. p. 145, _et seq._ The statutes enacted
that no member was to settle in any town where another member was
already settled.

~Continuo~ = Basso Continuo, the bass of a composition for voices.

~Oboe~ da Caccia. Hunting oboe, bent like a knee.

~Choral~ is the German name for the Plainsong of the Roman Church.

~Viola~ d'amore. A tenor viol of a specially agreeable and silvery tone.

~Violino~ piccolo. A small violin.

~Viola~ pomposa, an instrument invented by Bach.
"""


def test_parse_gutenberg_glossary_heads_and_aliases():
    entries = parse_glossary_entries(BACH_GLOSSARY, chapter="sec-019")
    by_name = {row["name"]: row for row in entries}
    assert "Ahle" in by_name
    assert by_name["Ahle"]["summary"].startswith("Ahle, Joh. Rudolph")
    assert by_name["Cembalo"]["aliases"] == ["clavicymbal", "clavessin", "clavecin"]
    assert by_name["Continuo"]["aliases"] == ["Basso Continuo"]
    assert "modern grand piano" in by_name["Cembalo"]["summary"]
    assert by_name["College of Instrumental Musicians of Upper and Lower Saxony"][
        "chapter"
    ] == "sec-019"
    assert by_name["Oboe da Caccia"]["summary"].startswith("Oboe da Caccia.")
    assert "tenor viol" in by_name["Viola d'amore"]["summary"]
    assert by_name["Choral"]["summary"].startswith("Choral is the German name")
    assert "small violin" in by_name["Violino piccolo"]["summary"]
    assert "invented by Bach" in by_name["Viola pomposa"]["summary"]
    assert "modern grand piano" in by_name["Clavicymbal"]["summary"]


def test_see_glossary_pointer_expands_to_entry_body():
    entries = parse_glossary_entries(BACH_GLOSSARY)
    body = expand_see_glossary_body(
        'See Glossary, "College of Instrumental Musicians."',
        entries,
    )
    assert body.startswith("College of Instrumental Musicians")
    assert "Spitta" in body
    assert "See Glossary" not in body
    cembalo = expand_see_glossary_body('See Glossary, "Cembalo."', entries)
    assert "clavicymbal" in cembalo
    inferred = expand_see_glossary_body(
        "See Glossary.",
        entries,
        host_text="He studied with Böhm in Lüneburg.[1]",
    )
    assert inferred.startswith("Böhm, Georg")
    vietnamese = expand_see_glossary_body('Xem Bảng chú giải, «Cembalo».', entries)
    assert "grand piano" in vietnamese


def test_see_glossary_without_a_match_stays_a_pointer():
    entries = parse_glossary_entries(BACH_GLOSSARY)
    original = "See Glossary, \"Not a real term.\""
    assert expand_see_glossary_body(original, entries) == original
    assert expand_see_glossary_body("A normal footnote about Spitta.", entries) == (
        "A normal footnote about Spitta."
    )


def test_attach_edition_publishes_glossary_cards_and_resolves_notes():
    edition = {
        "edition_format": "ref/1",
        "edition_hash": "a" * 64,
        "content_kind": "prose",
        "reading_markdown": "A second son.[1]",
        "blocks": [
            {
                "type": "paragraph",
                "text": "A second son.[1]",
                "spans": [
                    {
                        "style": "footnote",
                        "start": 14,
                        "end": 17,
                        "text": "[1]",
                        "note": 'See Glossary, "College of Instrumental Musicians."',
                    }
                ],
            }
        ],
        "_chapters": [
            {
                "chapter_id": "ch-001",
                "title": "Chapter I",
                "reading_markdown": "A second son.[1]",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "A second son.[1]",
                        "spans": [
                            {
                                "style": "footnote",
                                "start": 14,
                                "end": 17,
                                "text": "[1]",
                                "note": 'See Glossary, "College of Instrumental Musicians."',
                            }
                        ],
                    }
                ],
                "notes": [
                    {
                        "marker": "[1]",
                        "body": 'See Glossary, "College of Instrumental Musicians."',
                    }
                ],
            },
            {
                "chapter_id": "sec-019",
                "title": "Glossary",
                "kind": "back_matter",
                "reading_markdown": BACH_GLOSSARY,
                "blocks": [{"type": "paragraph", "text": BACH_GLOSSARY}],
            },
        ],
    }
    payload: dict = {"raw_text": "x"}
    _attach_edition(payload, {"edition": edition})
    note = payload["notes"][0]
    assert note["marker"] == "[1]"
    assert note["kind"] == "footnote"
    assert "Spitta" in note["body"]
    assert "See Glossary" not in note["body"]
    span_note = payload["chapters"][0]["blocks"][0]["spans"][0]["note"]
    assert "Spitta" in span_note
    terms = {row["name"]: row for row in payload["glossary"]}
    assert terms["Cembalo"]["kind"] == "glossary"
    assert terms["Cembalo"]["group_label"] == "Thuật ngữ"
    assert "clavicymbal" in terms["Cembalo"]["aliases"]
    assert payload["chapters"][1]["title"] == "Glossary"


def test_attach_book_glossary_merges_without_clobbering_existing_cards():
    payload = {
        "glossary": [
            {
                "name": "Gordian [17]",
                "aliases": ["[17]"],
                "summary": "A knot.",
                "kind": "footnote",
                "group_label": "Chú thích",
                "marker": "[17]",
                "anchor": "Gordian",
                "chapter": "I",
            }
        ],
        "notes": [
            {
                "kind": "footnote",
                "marker": "[1]",
                "body": 'See Glossary, "Cembalo."',
                "host_text": "He played the cembalo.[1]",
            }
        ],
        "chapters": [],
    }
    edition = {
        "_chapters": [
            {
                "chapter_id": "sec-019",
                "title": "Bảng chú giải",
                "reading_markdown": BACH_GLOSSARY,
            }
        ]
    }
    attach_book_glossary(payload, edition)
    assert payload["glossary"][0]["name"] == "Gordian [17]"
    assert any(row["name"] == "Cembalo" for row in payload["glossary"])
    assert "grand piano" in payload["notes"][0]["body"]


def test_real_bach_glossary_resolves_college_of_instrumental_musicians():
    import json

    path = Path("corpus/translations/bach--abdy_williams/segments/chglossary.json")
    source = json.loads(path.read_text(encoding="utf-8"))["source_text"]
    entries = parse_glossary_entries(source)
    assert len(entries) > 40
    body = expand_see_glossary_body(
        'See Glossary, "College of Instrumental Musicians."',
        entries,
    )
    assert "no member was to settle" in body
    names = {row["name"] for row in entries}
    assert "Buxtehude" in names
    assert "Cembalo" in names
    assert "Continuo" in names
    assert any("Basso Continuo" in (row.get("aliases") or []) for row in entries)
    assert "Viola d'amore" in {_fold_name(name) for name in names}
    assert "Violino piccolo" in names
    assert any(name.startswith("College of Instrumental Musicians") for name in names)


def _fold_name(name: str) -> str:
    return name.replace("’", "'").replace("‘", "'")
