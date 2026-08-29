"""REF v1.6 — general rule fixes for LLM warn samples."""

from __future__ import annotations

from pathlib import Path

from knowledgehub.edition.inline_spans import annotate_inline_spans
from knowledgehub.edition.ref_parser import parse_manuscript_to_ref

CORPUS = Path(__file__).resolve().parent / "fixtures" / "ref_corpus"


def test_aquinas_objections_are_paragraphs():
    raw = (CORPUS / "en" / "aquinas_summa.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="scholastic", strip_first=True)
    objections = [b for b in edition["blocks"] if str(b.get("text", "")).startswith("Objection")]
    assert objections
    assert all(b["type"] == "paragraph" for b in objections)


def test_hamlet_act_scene_separate_and_dialogue_joined():
    raw = (CORPUS / "en" / "shakespeare_hamlet.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    headings = [b for b in edition["blocks"] if b["type"] == "heading"]
    act = [b for b in headings if b.get("text") == "ACT I"]
    scene = [b for b in headings if str(b.get("text", "")).startswith("SCENE I.")]
    assert act and scene
    assert act[0].get("level") == 1
    assert scene[0].get("level") == 2
    joined = [b for b in edition["blocks"] if b.get("type") == "dialogue" and "sick at heart" in b.get("text", "")]
    assert joined, "dialogue continuation should merge into one block"


def test_darwin_dr_hooker_joined():
    raw = (CORPUS / "en" / "darwin_origin.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    md = edition["reading_markdown"]
    assert "Dr. Hooker" in md.replace("\n", " ")
    assert "No doubt errors" in md.replace("\n", " ")


def test_homer_opening_stanza():
    raw = (CORPUS / "en" / "homer_iliad.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    stanzas = [b for b in edition["blocks"] if b["type"] == "stanza"]
    assert stanzas
    assert "Declare, O Muse!" in stanzas[0]["text"]
    assert "\n" in stanzas[0]["text"]


def test_montesquieu_contents_metadata():
    raw = (CORPUS / "en" / "montesquieu_spirit.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    meta = [b for b in edition["blocks"] if b["type"] == "metadata" and "CONTENTS" in b.get("text", "")]
    assert meta
    assert "CHAPTER" in meta[0]["text"]


def test_paine_paren_aside_full_span():
    text = (
        "As a long and violent abuse of power, is generally the Means of calling the right of it "
        "in question (and in Matters too which might never have been thought of, had not the "
        "Sufferers been aggravated into the inquiry) and the exercise of it."
    )
    spans = annotate_inline_spans(text)
    aside = [s for s in spans if s.style == "paren_aside"]
    assert len(aside) == 1
    assert aside[0].text.startswith("(") and aside[0].text.endswith(")")


def test_poe_body_not_metadata():
    raw = (CORPUS / "en" / "poe_raven.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    meta = [b for b in edition["blocks"] if b["type"] == "metadata"]
    assert not meta
    prose = " ".join(b.get("text", "") for b in edition["blocks"] if b["type"] == "paragraph")
    assert "melancholy House of Usher" in prose
    assert "sojourn of some weeks" in prose


def test_bunyan_bracket_cites_joined():
    raw = (CORPUS / "en" / "bunyan_pilgrim.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    md = edition["reading_markdown"]
    assert "[Job 33:23]" in md.replace("\n", " ")
    assert "[Heb. 9:27]" in md.replace("\n", " ")
    assert "33:23]" not in md.split("[Job 33:23]")[0][-20:]
