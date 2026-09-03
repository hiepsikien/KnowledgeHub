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
    from knowledgehub.edition.serialize import edition_hash

    assert payload["edition_hash"] == edition_hash(
        list(edition["blocks"] or []),
        chapters=list(edition["_chapters"]),
    )
    assert payload["edition_hash"] != "a" * 64


def test_attach_edition_filters_book_level_hidden_blocks():
    edition = {
        "edition_format": "ref/1",
        "edition_hash": "a" * 64,
        "content_kind": "prose",
        "reading_markdown": "Visible body.",
        "blocks": [
            {"type": "paragraph", "text": "Weimar", "hidden": True, "role": "aside"},
            {"type": "heading", "text": "CHAPTER III", "level": 1, "suppress_in_reader": True},
            {"type": "paragraph", "text": "Visible body."},
        ],
        "split_hints": [
            {"type": "heading", "level": 1, "block_index": 1, "text": "CHAPTER III"},
        ],
        "_chapters": [
            {
                "chapter_id": "ch-001",
                "title": "Chapter III",
                "reading_markdown": "Visible body.",
                "blocks": [
                    {"type": "paragraph", "text": "Weimar", "hidden": True, "role": "aside"},
                    {"type": "paragraph", "text": "Visible body."},
                ],
            }
        ],
    }
    payload: dict = {"raw_text": "x"}
    _attach_edition(payload, {"edition": edition})
    assert [b["text"] for b in payload["blocks"]] == ["Visible body."]
    assert payload["chapters"][0]["blocks"][0]["text"] == "Visible body."
    assert not any(h.get("text") == "CHAPTER III" for h in payload["split_hints"])


def test_edition_hash_includes_chapter_id_and_title():
    from knowledgehub.edition.serialize import edition_hash

    blocks = [{"type": "paragraph", "text": "Hello"}]
    blocks_only = edition_hash(blocks)
    with_chapters = edition_hash(
        blocks,
        chapters=[{"chapter_id": "sec-001", "title": "I. THE FUNCTION OF CRITICISM AT THE PRESENT TIME."}],
    )
    other_title = edition_hash(
        blocks,
        chapters=[{"chapter_id": "sec-001", "title": "_FIRST AND SECOND SERIES COMPLETE_"}],
    )
    assert len(with_chapters) == 64
    assert with_chapters != blocks_only
    assert with_chapters != other_title


def test_attach_edition_includes_figure_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(tmp_path))
    dest = tmp_path / "assets" / "bach--abdy_williams"
    dest.mkdir(parents=True)
    (dest / "illoa001.png").write_bytes(b"png-bytes")
    figure = {
        "type": "paragraph",
        "role": "figure",
        "text": "Bach",
        "src": "/assets/bach--abdy_williams/illoa001.png",
    }
    edition = {
        "edition_format": "ref/1",
        "edition_hash": "a" * 64,
        "content_kind": "prose",
        "reading_markdown": "Bach",
        "blocks": [figure],
        "_chapters": [
            {
                "chapter_id": "ch-001",
                "title": "Front matter",
                "reading_markdown": "Bach",
                "blocks": [figure],
            }
        ],
    }
    payload: dict = {"hub_work_id": "bach--abdy_williams", "raw_text": "x"}
    _attach_edition(payload, {"edition": edition})
    assert payload["assets"]
    assert payload["assets"][0]["filename"] == "illoa001.png"
    assert payload["assets"][0]["content_type"] == "image/png"
    assert payload["chapters"][0]["blocks"][0]["src"].endswith("illoa001.png")
