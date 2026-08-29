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
    raw = (CORPUS / "en" / "machiavelli_prince.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    types = _types(edition)
    assert types.get("metadata", 0) >= 1
    assert types.get("heading", 0) <= 3
    assert "CHAPTER I." in (edition["blocks"][0].get("text") or "")


def test_pg_toc_list_not_false_headings():
    raw = (CORPUS / "en" / "melville_moby.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    types = _types(edition)
    assert types.get("metadata", 0) >= 1
    assert types.get("heading", 0) <= 2


def test_part_of_not_heading():
    raw = (CORPUS / "en" / "paine_common_sense.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=True)
    headings = [b["text"] for b in edition["blocks"] if b["type"] == "heading"]
    assert not any(h.lower().startswith("part of his property") for h in headings)


def test_publisher_imprint_merged():
    raw = (CORPUS / "en" / "locke_second_treatise.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    imprint = " ".join(str(b.get("text") or "") for b in edition["blocks"])
    assert "LONDON PRINTED MDCLXXXVIII" in imprint
    assert "REPRINTED" in imprint
