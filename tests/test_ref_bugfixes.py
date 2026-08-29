from __future__ import annotations

import json

from knowledgehub.edition.cache import load_cached_edition, save_cached_edition
from knowledgehub.edition.label_rules import LineLabel
from knowledgehub.edition.lines import TextLine
from knowledgehub.edition.merge_blocks import labels_to_blocks
from knowledgehub.edition.ref import build_read_edition
from knowledgehub.edition.ref_schema import REF_PARSER_VERSION


def test_cache_miss_when_parser_version_stale(tmp_path):
    corpus = tmp_path / "corpus"
    root = corpus / "editions/demo--work/abc123"
    root.mkdir(parents=True)
    (root / "blocks.json").write_text(
        json.dumps({"edition_format": "ref/1", "blocks": [{"type": "paragraph", "text": "old"}]}),
        encoding="utf-8",
    )
    (root / "cache_meta.json").write_text(
        json.dumps({"ref_parser_version": "1.0"}),
        encoding="utf-8",
    )
    assert load_cached_edition("demo--work", "abc123", corpus=corpus) is None

    edition = {"edition_format": "ref/1", "blocks": [{"type": "paragraph", "text": "new"}]}
    save_cached_edition("demo--work", "abc123", edition, corpus=corpus)
    meta = json.loads((root / "cache_meta.json").read_text(encoding="utf-8"))
    assert meta["ref_parser_version"] == REF_PARSER_VERSION
    loaded = load_cached_edition("demo--work", "abc123", corpus=corpus)
    assert loaded["blocks"][0]["text"] == "new"


def test_cache_miss_when_meta_missing(tmp_path):
    corpus = tmp_path / "corpus"
    root = corpus / "editions/demo--work/legacy"
    root.mkdir(parents=True)
    (root / "blocks.json").write_text(
        json.dumps({"edition_format": "ref/1", "blocks": [{"type": "paragraph", "text": "legacy"}]}),
        encoding="utf-8",
    )
    assert load_cached_edition("demo--work", "legacy", corpus=corpus) is None


def test_orphan_speaker_cue_becomes_stage_direction():
    lines = [
        TextLine(0, "HAMLET.", 0, 7, False, 0),
        TextLine(1, "The rest is silence.", 8, 28, True, 0),
    ]
    labels = [
        LineLabel(0, "speaker_cue", None, False, 0.9, "rule"),
        LineLabel(1, "prose", None, False, 0.9, "rule"),
    ]
    blocks = labels_to_blocks(lines, labels)
    assert blocks[0]["type"] == "stage_direction"
    assert blocks[0]["text"] == "HAMLET."
    assert blocks[1]["type"] == "paragraph"


def test_read_edition_package_rebuilds_on_parser_version(tmp_path, monkeypatch):
    from knowledgehub.edition.read_edition import build_read_edition_package, read_edition_dir

    corpus = tmp_path / "corpus"
    raw_dir = corpus / "sources/grotius/raw"
    raw_dir.mkdir(parents=True)
    fixture = (
        __import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "grotius_pg_snippet.txt"
    )
    (raw_dir / "freedom_of_the_seas.txt").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    catalog = corpus / "catalog"
    catalog.mkdir()
    works = [
        {
            "id": "grotius--freedom_of_the_seas",
            "title": "Freedom",
            "author_id": "grotius",
            "language": "en",
            "license": "public_domain_usa_gutenberg",
            "content_file": "sources/grotius/raw/freedom_of_the_seas.txt",
            "content_hash": "hash1",
            "rights": {"consumers": {"read": "allowed"}},
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(json.dumps([{"id": "grotius", "name": "Grotius"}]), encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))

    first = build_read_edition_package("grotius--freedom_of_the_seas", corpus=corpus)
    edition_hash = first["manifest"]["edition_hash"]
    package_dir = read_edition_dir("grotius--freedom_of_the_seas", edition_hash, corpus=corpus)
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["ref_parser_version"] = "0.1"
    (package_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    second = build_read_edition_package("grotius--freedom_of_the_seas", corpus=corpus)
    assert second["built"] is True
    refreshed = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    assert refreshed["ref_parser_version"] == REF_PARSER_VERSION
