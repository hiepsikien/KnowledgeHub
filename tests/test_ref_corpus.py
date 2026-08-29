from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledgehub.edition.ref_parser import assert_valid_edition, parse_manuscript_to_ref
from knowledgehub.edition.serialize import blocks_to_markdown

CORPUS_DIR = Path(__file__).resolve().parent / "fixtures" / "ref_corpus"
MANIFEST = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
EXPECTATIONS = json.loads((CORPUS_DIR / "expectations.json").read_text(encoding="utf-8"))


def _load_sample(entry: dict) -> tuple[str, dict]:
    text = (CORPUS_DIR / entry["file"]).read_text(encoding="utf-8")
    return text, entry


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda e: e["id"])
def test_corpus_parses_to_valid_ref(entry: dict) -> None:
    text, meta = _load_sample(entry)
    edition, report = parse_manuscript_to_ref(
        text,
        language=meta["language"],
        family=meta.get("family"),
        strip_first=meta.get("family") == "gutenberg",
    )
    assert report["validation_errors"] == [], report["validation_errors"]
    assert_valid_edition(edition)
    assert edition["edition_format"] == "ref/1"
    assert len(edition["edition_hash"]) == 64
    assert blocks_to_markdown(edition["blocks"]) == edition["reading_markdown"]


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda e: e["id"])
def test_corpus_meets_expectations(entry: dict) -> None:
    exp = EXPECTATIONS.get(entry["id"])
    assert exp is not None, f"missing expectations for {entry['id']}"

    text, meta = _load_sample(entry)
    edition, _ = parse_manuscript_to_ref(
        text,
        language=meta["language"],
        family=meta.get("family"),
        strip_first=meta.get("family") == "gutenberg",
    )
    blocks = edition["blocks"]
    md = edition["reading_markdown"]
    types = {b["type"] for b in blocks}
    span_styles: dict[str, int] = {}
    for block in blocks:
        for span in block.get("spans") or []:
            style = span["style"]
            span_styles[style] = span_styles.get(style, 0) + 1

    assert len(blocks) >= exp["min_blocks"]
    assert len(blocks) <= exp["max_blocks"]
    for kind in exp["required_types"]:
        assert kind in types, f"{entry['id']}: missing block type {kind!r}, got {types}"
    assert edition["content_kind"] == exp["content_kind"]

    if "min_footnotes" in exp:
        assert span_styles.get("footnote", 0) >= exp["min_footnotes"]
    if "min_span_styles" in exp:
        for style, minimum in exp["min_span_styles"].items():
            assert span_styles.get(style, 0) >= minimum, (
                f"{entry['id']}: expected ≥{minimum} {style!r}, got {span_styles}"
            )
    for fragment in exp.get("required_in_markdown", []):
        assert fragment in md, f"{entry['id']}: {fragment!r} not in reading_markdown"
    if joined := exp.get("required_joined"):
        assert joined in md, f"{entry['id']}: joined fragment {joined!r} missing"


def test_corpus_manifest_covers_expectations() -> None:
    manifest_ids = {e["id"] for e in MANIFEST}
    for sample_id in EXPECTATIONS:
        assert sample_id in manifest_ids, f"expectations entry {sample_id!r} not in manifest"


def test_corpus_language_split() -> None:
    en = [e for e in MANIFEST if e["language"] == "en"]
    vi = [e for e in MANIFEST if e["language"] == "vi"]
    assert len(en) >= 5, "need ≥5 EN corpus samples"
    assert len(vi) >= 5, "need ≥5 VI corpus samples"
