"""REF v1.7 — QA-driven fixes: TOC, PG prose indent, speaker cues, quotes."""

from __future__ import annotations

from pathlib import Path

from knowledgehub.edition.ref_parser import parse_manuscript_to_ref

CORPUS = Path(__file__).resolve().parent / "fixtures" / "ref_corpus"
CORPUS_B = Path(__file__).resolve().parent / "fixtures" / "ref_corpus_b"


def test_smith_wealth_indented_prose_not_stanza():
    raw = (CORPUS / "en" / "smith_wealth.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    assert not any(b["type"] == "stanza" for b in edition["blocks"])
    assert "consumes, and which consist" in edition["reading_markdown"].replace("\n", " ")


def test_twain_contents_single_metadata():
    raw = (CORPUS / "en" / "twain_huckleberry.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    meta = [b for b in edition["blocks"] if b["type"] == "metadata" and "CONTENTS" in b.get("text", "")]
    assert meta
    assert "CHAPTER II." in meta[0]["text"]
    chapter_headings = sum(1 for b in edition["blocks"] if b["type"] == "heading" and "CHAPTER" in b.get("text", ""))
    assert chapter_headings <= 5


def test_shelley_letter_chapter_toc_metadata():
    raw = (CORPUS / "en" / "shelley_frankenstein.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    meta = [b for b in edition["blocks"] if b["type"] == "metadata"]
    assert meta
    assert "Letter 1" in meta[0]["text"]
    assert "Chapter 24" in meta[0]["text"] or "Chapter 2" in meta[0]["text"]


def test_aquinas_electronic_note_not_heading():
    raw = (CORPUS_B / "en" / "aquinas_summa_part2_2.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="scholastic", strip_first=True)
    note = [b for b in edition["blocks"] if b["type"] == "metadata" and "NOTE TO THIS ELECTRONIC" in b.get("text", "")]
    assert note
    assert not any(
        b["type"] == "heading" and b.get("text", "").startswith("Prologue, and the numbers")
        for b in edition["blocks"]
    )


def test_blackstone_dedication_not_dialogue():
    raw = (CORPUS_B / "en" / "blackstone_commentaries_book1.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    assert not any(b.get("type") == "dialogue" and b.get("text") == "TO" for b in edition["blocks"])
    assert not any(b.get("type") == "dialogue" and b.get("speaker") == "M. DCC. LXV." for b in edition["blocks"])


def test_dostoevsky_inner_monologue_joined():
    raw = (CORPUS / "en" / "dostoevsky_crime.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    quotes = [b for b in edition["blocks"] if b["type"] == "blockquote"]
    assert len(quotes) <= 2
    joined = " ".join(b.get("text", "") for b in edition["blocks"] if b["type"] in {"paragraph", "blockquote"})
    assert "It would be interesting" in joined.replace("\n", " ")


def test_tat_den_vi_toc_metadata():
    raw = (CORPUS / "vi" / "tat_den.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="vi", family="plain", strip_first=False)
    meta = [b for b in edition["blocks"] if b["type"] == "metadata" and "Mục lục" in b.get("text", "")]
    assert meta
    assert "XX" in meta[0]["text"] or "XV" in meta[0]["text"]
