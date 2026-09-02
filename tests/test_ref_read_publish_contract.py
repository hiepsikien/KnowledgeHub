from __future__ import annotations

from knowledgehub.edition.footnotes import notes_for_read_publish
from knowledgehub.read_publish import _attach_edition, _chapters_for_read_publish


def test_notes_for_read_publish_prefers_chapter_span_notes():
    edition = {
        "blocks": [
            {
                "type": "paragraph",
                "text": "Seneca[1] says so.",
                "spans": [
                    {"style": "footnote", "start": 6, "end": 9, "text": "[1]", "note": "Natural Questions."}
                ],
            }
        ],
        "notes": [{"marker": "[9]", "body": "stale edition note"}],
    }
    chapters = [
        {
            "chapter_id": "ch-001",
            "title": "Chapter I",
            "blocks": edition["blocks"],
            "notes": [],
            "reading_markdown": "Seneca[1] says so.",
        }
    ]
    notes = notes_for_read_publish(edition, chapters=chapters)
    assert len(notes) == 1
    assert notes[0]["marker"] == "[1]"
    assert notes[0]["body"] == "Natural Questions."
    assert notes[0]["chapter"] == "ch-001"
    assert notes[0]["label"] == "[1]"


def test_notes_for_read_publish_span_wins_over_stale_chapter_notes():
    """HITL writes body on span.note; chapter notes may still hold the parse-time body."""
    chapters = [
        {
            "chapter_id": "ch-002",
            "title": "Chapter II",
            "notes": [
                {
                    "marker": "[1]",
                    "body": "stale parse-time body",
                    "chapter": "II",
                    "label": "[1]",
                }
            ],
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Arnold[1] wrote.",
                    "spans": [
                        {
                            "style": "footnote",
                            "start": 6,
                            "end": 9,
                            "text": "[1]",
                            "note": "HITL-corrected body.",
                        }
                    ],
                }
            ],
            "reading_markdown": "Arnold[1] wrote.",
        }
    ]
    notes = notes_for_read_publish({}, chapters=chapters)
    assert len(notes) == 1
    assert notes[0]["body"] == "HITL-corrected body."
    assert notes[0]["chapter"] == "ch-002"
    assert notes[0]["marker"] == "[1]"


def test_attach_edition_sends_chapters_and_notes():
    edition = {
        "edition_format": "ref/1",
        "edition_hash": "a" * 64,
        "content_kind": "prose",
        "reading_markdown": "Chapter I\n\nHello[1].",
        "blocks": [{"type": "paragraph", "text": "Hello[1].", "spans": []}],
        "split_hints": [],
        "_chapters": [
            {
                "chapter_id": "ch-001",
                "title": "Chapter I",
                "reading_markdown": "Hello[1].",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "Hello[1].",
                        "spans": [
                            {
                                "style": "footnote",
                                "start": 5,
                                "end": 8,
                                "text": "[1]",
                                "note": "A note.",
                            }
                        ],
                    }
                ],
                "notes": [
                    {
                        "marker": "[1]",
                        "body": "stale chapter note",
                        "chapter": "I",
                    }
                ],
                "word_count": 1,
            }
        ],
    }
    payload: dict = {"raw_text": "x"}
    _attach_edition(payload, {"edition": edition})
    assert payload["edition_format"] == "ref/1"
    assert payload["chapters"][0]["id"] == "ch-001"
    assert payload["chapters"][0]["content"] == "Hello[1]."
    assert payload["chapters"][0]["blocks"]
    assert payload["notes"][0]["body"] == "A note."
    assert payload["notes"][0]["chapter"] == "ch-001"
    assert _chapters_for_read_publish(edition)[0]["title"] == "Chapter I"
