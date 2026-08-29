from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledgehub.edition.inline_spans import annotate_blocks, annotate_inline_spans, detect_quotation_profile
from knowledgehub.edition.ref import build_read_edition

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "inline_quotation_samples.json"


def _load_samples() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def _styles(text: str) -> list[tuple[str, str]]:
    return [(s.text, s.style) for s in annotate_inline_spans(text)]


@pytest.mark.parametrize("sample", _load_samples(), ids=lambda s: s["id"])
def test_inline_quotation_styles(sample: dict) -> None:
    found = _styles(sample["text"])
    for fragment, style in sample["expect"]:
        matches = [(t, st) for t, st in found if fragment in t and st == style]
        assert matches, f"{sample['id']}: expected {style!r} containing {fragment!r}, got {found}"


def test_footnote_not_confused_with_bracket_note():
    text = "See empty.[168] For they intimate as clearly as they can."
    styles = {s.text: s.style for s in annotate_inline_spans(text)}
    assert styles["[168]"] == "footnote"


def test_bracket_note_not_footnote():
    text = "[The Cambridge Modern History, I, 23-24, has a good paragraph upon this famous Papal Bull]"
    styles = {s.text: s.style for s in annotate_inline_spans(text)}
    assert styles[text] == "bracket_note"


def test_paren_cite_not_footnote():
    text = "Victoria (as Victoria also says) rejected the claim, see Politics,[148]."
    found = annotate_inline_spans(text)
    assert any(s.style == "paren_cite" and "Victoria also says" in s.text for s in found)
    assert any(s.style == "footnote" and s.text == "[148]" for s in found)


def test_grotius_snippet_profile():
    raw = (Path(__file__).resolve().parent / "fixtures" / "grotius_pg_snippet.txt").read_text(encoding="utf-8")
    edition, report = build_read_edition(
        raw,
        family="gutenberg",
        language="en",
        work_id="grotius--freedom_of_the_seas",
    )
    profile = edition.get("quotation_profile") or report.get("quotation_profile") or {}
    assert profile.get("detector") == "rule"
    assert profile.get("italic_spans", 0) >= 2
    blocks_with_spans = [b for b in edition["blocks"] if b.get("spans")]
    assert blocks_with_spans


def test_quotation_profile_counts_footnotes():
    en = _load_samples()[:5]
    profile = detect_quotation_profile([s["text"] for s in en])
    assert profile["footnote_style"] == "bracket"
    assert profile["footnote_count"] >= 4


def test_annotate_blocks_preserves_text():
    blocks = [{"type": "paragraph", "text": "Greeks[178] and (Politics)[148]"}]
    out, profile = annotate_blocks(blocks)
    assert out[0]["text"] == blocks[0]["text"]
    styles = {s["style"] for s in out[0]["spans"]}
    assert "footnote" in styles
    assert "paren_cite" in styles
    assert profile["footnote_count"] >= 2
