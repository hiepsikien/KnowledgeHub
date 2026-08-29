from __future__ import annotations

from pathlib import Path

from knowledgehub.edition.ref_parser import parse_manuscript_to_ref

CORPUS = Path(__file__).resolve().parent / "fixtures" / "ref_corpus"


def _types(edition: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for block in edition["blocks"]:
        kind = block["type"]
        out[kind] = out.get(kind, 0) + 1
    return out


def test_pg_toc_excerpt_becomes_metadata():
    raw = (CORPUS / "en" / "pg_toc_list_sample.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    types = _types(edition)
    assert types.get("metadata", 0) >= 1
    assert types.get("heading", 0) <= 3
    assert "CHAPTER I." in (edition["blocks"][0].get("text") or "")


def test_pg_body_excerpt_is_prose():
    raw = (CORPUS / "en" / "melville_moby.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    types = _types(edition)
    assert types.get("paragraph", 0) >= 3
    assert "Ishmael" in edition["reading_markdown"]


def test_pg_toc_list_not_false_headings():
    raw = (CORPUS / "en" / "pg_toc_list_sample.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    types = _types(edition)
    assert types.get("metadata", 0) >= 1
    assert types.get("heading", 0) <= 2


def test_part_of_not_heading():
    raw = (CORPUS / "en" / "paine_common_sense.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    headings = [b["text"] for b in edition["blocks"] if b["type"] == "heading"]
    assert not any(h.lower().startswith("part of his property") for h in headings)


def test_chapter_line_not_speaker_cue():
    from knowledgehub.edition.structure import is_speaker_cue

    assert not is_speaker_cue("CHAPTER I.")
    assert not is_speaker_cue("CHAPTER XLII.")
    assert is_speaker_cue("HAMLET.")


def test_hamlet_dramatis_grouped():
    raw = (CORPUS / "en" / "shakespeare_hamlet.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    meta = [b for b in edition["blocks"] if b["type"] == "metadata"]
    assert meta, "expected dramatis metadata block"
    assert "HAMLET" in meta[0]["text"]
    assert "Dramatis" in meta[0]["text"] or "Person" in meta[0]["text"]


def test_twain_chapter_not_dialogue():
    path = CORPUS / "en" / "twain_huckleberry.txt"
    if not path.exists():
        return
    raw = path.read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    headings = [b for b in edition["blocks"] if b["type"] == "heading"]
    dialogues = [b for b in edition["blocks"] if b["type"] == "dialogue"]
    assert any("CHAPTER" in b.get("text", "") for b in headings) or not dialogues[:3]
    raw = (CORPUS / "en" / "locke_second_treatise.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    imprint = " ".join(str(b.get("text") or "") for b in edition["blocks"])
    assert "LONDON PRINTED MDCLXXXVIII" in imprint
    assert "REPRINTED" in imprint
