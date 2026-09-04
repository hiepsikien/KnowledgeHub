from __future__ import annotations

import json
from pathlib import Path

from knowledgehub.edition.glossary import (
    attach_published_glossary,
    is_glossary_chapter,
    lookup_entry,
    parse_glossary_blocks,
    parse_glossary_pointer,
    resolve_pointer_body,
)
from knowledgehub.read_publish import _attach_edition


GLOSSARY_BLOCKS = [
    {"type": "paragraph", "text": "Glossary"},
    {
        "type": "paragraph",
        "text": "~Cembalo~, or clavicymbal, or clavessin, or clavecin, for which Bach wrote his clavier works, was in shape like the modern grand piano.",
        "spans": [{"start": 0, "end": 9, "style": "strong", "text": "~Cembalo~"}],
    },
    {
        "type": "paragraph",
        "text": "The cembalo was used to play the basso continuo. Other names were Gravecymbalum, Flügel.",
    },
    {
        "type": "paragraph",
        "text": "~Clavicymbal.~ See Cembalo.",
        "spans": [{"start": 0, "end": 14, "style": "strong", "text": "~Clavicymbal.~"}],
    },
    {
        "type": "paragraph",
        "text": "~College~ of Instrumental Musicians of Upper and Lower Saxony. The statutes enacted that no member was to settle in any town where another member was already settled.",
        "spans": [{"start": 0, "end": 9, "style": "strong", "text": "~College~"}],
    },
    {
        "type": "paragraph",
        "text": "~Continuo~ = Basso Continuo, the bass of a composition for voices or instruments or both.",
        "spans": [{"start": 0, "end": 10, "style": "strong", "text": "~Continuo~"}],
    },
    {
        "type": "paragraph",
        "text": "~Florilegium~ Portense, a work containing 115 cantiones.",
        "spans": [{"start": 0, "end": 13, "style": "strong", "text": "~Florilegium~"}],
    },
    {
        "type": "paragraph",
        "text": "~Mizler~, von Kolof, Doctor of Philosophy.",
        "spans": [{"start": 0, "end": 8, "style": "strong", "text": "~Mizler~"}],
    },
    {
        "type": "paragraph",
        "text": "~Positiv.~ The name given to that portion of an organ which corresponds to our choir organ.",
        "spans": [{"start": 0, "end": 10, "style": "strong", "text": "~Positiv.~"}],
    },
    {
        "type": "paragraph",
        "text": "~Rück-positiv.~ The name given to the choir manual when its pipes stand behind the rest of the organ.",
        "spans": [{"start": 0, "end": 16, "style": "strong", "text": "~Rück-positiv.~"}],
    },
    {
        "type": "paragraph",
        "text": "~Viola~ da gamba. Leg viol, the bass of the viol family.",
        "spans": [{"start": 0, "end": 7, "style": "strong", "text": "~Viola~"}],
    },
]


def test_parse_glossary_pointer_en_and_vi():
    assert parse_glossary_pointer('See Glossary, "College of Instrumental Musicians."') == (
        True,
        "College of Instrumental Musicians",
    )
    assert parse_glossary_pointer("See Glossary, Positiv.") == (True, "Positiv")
    assert parse_glossary_pointer("See Glossary.") == (True, "")
    assert parse_glossary_pointer("Xem Bảng chú giải, Positiv.") == (True, "Positiv")
    assert parse_glossary_pointer("Xem Bảng chú giải.") == (True, "")
    assert parse_glossary_pointer("Spitta, vol. i. p. 162.") == (False, "")


def test_parse_glossary_terms_and_aliases():
    entries = parse_glossary_blocks(GLOSSARY_BLOCKS)
    by_name = {row.name: row for row in entries}
    cembalo = lookup_entry("Cembalo", entries)
    assert cembalo is not None
    assert "clavicymbal" in [a.casefold() for a in cembalo.aliases]
    assert "clavecin" in [a.casefold() for a in cembalo.aliases]
    assert "Clavicymbal" not in by_name
    assert lookup_entry("clavicymbal", entries) is cembalo
    college = lookup_entry("College of Instrumental Musicians", entries)
    assert college is not None
    assert college.name.startswith("College of Instrumental Musicians")
    assert lookup_entry("Basso Continuo", entries) is not None
    assert lookup_entry("Viola da gamba", entries).name == "Viola da gamba"


def test_resolve_see_glossary_replaces_pointer():
    entries = parse_glossary_blocks(GLOSSARY_BLOCKS)
    body = resolve_pointer_body(
        'See Glossary, "College of Instrumental Musicians."',
        entries,
    )
    assert body is not None
    assert "statutes enacted" in body
    assert not body.lower().startswith("see glossary")
    positiv = resolve_pointer_body("See Glossary, Positiv.", entries)
    assert positiv is not None and "choir organ" in positiv
    vi = resolve_pointer_body("Xem Bảng chú giải, Positiv.", entries)
    assert vi == positiv


def test_bare_see_glossary_uses_host_term():
    entries = parse_glossary_blocks(GLOSSARY_BLOCKS)
    host = "They allowed Bach to purchase Bodenschatz's Florilegium Portense[44] for the scholars."
    body = resolve_pointer_body("See Glossary.", entries, host_text=host)
    assert body is not None
    assert "cantiones" in body
    organ = "RÜCKPOSITIV[81] 1. Principal, 8 ft."
    back = resolve_pointer_body("See Glossary.", entries, host_text=organ)
    assert back is not None
    assert "behind the rest of the organ" in back
    near_host = (
        "Amongst the obsolete instruments were viola da gamba,[60] "
        "and other consorts."
    )
    at = near_host.index("[60]")
    nearest = resolve_pointer_body("See Glossary.", entries, host_text=near_host, marker_at=at)
    assert nearest is not None
    assert "Leg viol" in nearest


def test_bach_glossary_chapter_parses_real_blocks():
    path = Path("corpus/translations/bach--abdy_williams/segments/chglossary.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = parse_glossary_blocks(list(doc.get("ref_blocks") or []))
    assert len(entries) >= 60
    assert lookup_entry("Buxtehude", entries) is not None
    assert lookup_entry("Orgel-büchlein", entries) is not None
    cembalo = lookup_entry("Cembalo", entries)
    assert cembalo is not None
    aliases = {a.casefold() for a in cembalo.aliases}
    assert "clavicymbal" in aliases
    assert "basso continuo" in {a.casefold() for a in lookup_entry("Continuo", entries).aliases}


def test_attach_edition_resolves_pointers_and_keeps_glossary_chapter():
    entries_src = parse_glossary_blocks(GLOSSARY_BLOCKS)
    college = lookup_entry("College of Instrumental Musicians", entries_src)
    assert college is not None
    edition = {
        "edition_format": "ref/1",
        "edition_hash": "a" * 64,
        "content_kind": "prose",
        "reading_markdown": "The guilds combined.[1]\n\nGlossary\n\n~Cembalo~, or clavicymbal.",
        "blocks": [
            {
                "type": "paragraph",
                "text": "The guilds combined.[1]",
                "spans": [
                    {
                        "style": "footnote",
                        "start": 19,
                        "end": 22,
                        "text": "[1]",
                        "note": 'See Glossary, "College of Instrumental Musicians."',
                    }
                ],
            },
            {"type": "paragraph", "text": "Glossary"},
            {
                "type": "paragraph",
                "text": "~Cembalo~, or clavicymbal, or clavecin, for which Bach wrote.",
            },
        ],
        "_chapters": [
            {
                "chapter_id": "ch-001",
                "title": "Chapter I",
                "reading_markdown": "The guilds combined.[1]",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "The guilds combined.[1]",
                        "spans": [
                            {
                                "style": "footnote",
                                "start": 19,
                                "end": 22,
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
                "chapter_id": "ch-019",
                "title": "Glossary",
                "kind": "back_matter",
                "reading_markdown": "Glossary\n\n~Cembalo~, or clavicymbal.",
                "blocks": GLOSSARY_BLOCKS,
            },
        ],
    }
    payload: dict = {"raw_text": "x"}
    _attach_edition(payload, {"edition": edition})
    assert any(ch["title"] == "Glossary" for ch in payload["chapters"])
    assert payload["notes"][0]["body"].startswith("College of Instrumental Musicians")
    assert "See Glossary" not in payload["notes"][0]["body"]
    assert payload["chapters"][0]["blocks"][0]["spans"][0]["note"].startswith(
        "College of Instrumental Musicians"
    )
    cards = [row for row in payload["glossary"] if row.get("kind") == "glossary"]
    names = {row["name"] for row in cards}
    assert "Cembalo" in names
    cembalo = next(row for row in cards if row["name"] == "Cembalo")
    assert cembalo["group_label"] == "Thuật ngữ"
    assert "clavicymbal" in [a.casefold() for a in cembalo["aliases"]]
    body_spans = [
        span.get("style")
        for block in payload["chapters"][0]["blocks"]
        for span in block.get("spans") or []
    ]
    assert "glossary" not in body_spans
    assert is_glossary_chapter(edition["_chapters"][1])


def test_attach_published_glossary_is_noop_without_chapter():
    payload = {
        "notes": [{"marker": "[1]", "body": "A real footnote.", "host_text": "Seneca[1]"}],
        "glossary": [],
        "blocks": [],
        "chapters": [],
    }
    edition = {"_chapters": [{"chapter_id": "ch-001", "title": "Chapter I", "blocks": []}]}
    attach_published_glossary(payload, edition)
    assert payload["notes"][0]["body"] == "A real footnote."
    assert payload["glossary"] == []
