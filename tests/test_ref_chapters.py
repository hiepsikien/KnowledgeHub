from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from knowledgehub.edition.read_edition import chapters_for_translation
from knowledgehub.edition.serialize import translation_source_from_blocks
from knowledgehub.translation.project import init_translation_project
from knowledgehub.translation.ref_chapters import sync_translation_chapters_from_ref

WORK = "bach--abdy_williams"
HASH = "deadbeefparsed01"


def _write_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, parsed: bool = True) -> Path:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    raw_dir = tmp_path / "sources/bach/raw"
    raw_dir.mkdir(parents=True)
    manuscript = (
        "CHAPTER I\n\n"
        "[Sidenote: _The Founder of the Family_]\n\n"
        "THE BACH FAMILY\n\n"
        "8. JOHANN AMBROSIUS, 1645-1695. 9. JOHANN CHRISTOPH, 1645-1693.\n\n"
        "Bach was born at Eisenach.\n\n"
        "CHAPTER II\n\n"
        "[Sidenote: Weimar]\n\n"
        "Bach went to Weimar in the next year of his appointment.\n"
    )
    (raw_dir / "abdy_williams.txt").write_text(manuscript, encoding="utf-8")
    works = [
        {
            "id": WORK,
            "title": "Bach",
            "author_id": "bach",
            "language": "en",
            "content_file": "sources/bach/raw/abdy_williams.txt",
            "content_hash": HASH,
            "gutenberg_id": "43650",
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(json.dumps([{"id": "bach", "name": "Bach"}]), encoding="utf-8")
    split = manuscript.index("CHAPTER II")
    pkg = tmp_path / "read-editions" / WORK / HASH
    pkg.mkdir(parents=True)
    structure = {
        "sections": [
            {
                "section_id": "sec-001",
                "title": "Chapter I",
                "kind": "chapter",
                "start_char": 0,
                "end_char": split - 1,
            },
            {
                "section_id": "sec-002",
                "title": "Chapter II",
                "kind": "chapter",
                "start_char": split,
                "end_char": len(manuscript) - 1,
            },
        ]
    }
    (pkg / "structure.json").write_text(json.dumps(structure), encoding="utf-8")
    if parsed:
        chapters_dir = pkg / "chapters"
        chapters_dir.mkdir()
        ch1 = {
            "chapter_id": "sec-001",
            "title": "Chapter I",
            "blocks": [
                {
                    "block_id": "sec-001:heading:ch",
                    "type": "heading",
                    "level": 1,
                    "text": "CHAPTER I",
                    "suppress_in_reader": True,
                },
                {
                    "block_id": "sec-001:p:aside",
                    "type": "paragraph",
                    "role": "aside",
                    "hidden": True,
                    "text": "_The Founder of the Family_",
                },
                {
                    "block_id": "sec-001:h:fam",
                    "type": "heading",
                    "level": 2,
                    "text": "THE BACH FAMILY",
                },
                {
                    "block_id": "sec-001:li:8",
                    "type": "list_item",
                    "role": "genealogy",
                    "text": "8. JOHANN AMBROSIUS, 1645-1695.",
                },
                {
                    "block_id": "sec-001:li:9",
                    "type": "list_item",
                    "role": "genealogy",
                    "text": "9. JOHANN CHRISTOPH, 1645-1693.",
                },
                {
                    "block_id": "sec-001:p:body",
                    "type": "paragraph",
                    "text": "Bach was born at Eisenach.",
                },
            ],
        }
        ch2 = {
            "chapter_id": "sec-002",
            "title": "Chapter II",
            "blocks": [
                {
                    "block_id": "sec-002:heading:ch",
                    "type": "heading",
                    "level": 1,
                    "text": "CHAPTER II",
                    "suppress_in_reader": True,
                },
                {
                    "block_id": "sec-002:p:aside",
                    "type": "paragraph",
                    "role": "aside",
                    "hidden": True,
                    "text": "Weimar",
                },
                {
                    "block_id": "sec-002:p:body",
                    "type": "paragraph",
                    "text": "Bach went to Weimar in the next year of his appointment.",
                },
            ],
        }
        (chapters_dir / "sec-001.json").write_text(json.dumps(ch1), encoding="utf-8")
        (chapters_dir / "sec-002.json").write_text(json.dumps(ch2), encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(tmp_path))
    return tmp_path


def test_translation_source_omits_hidden_sidenotes():
    blocks = [
        {"type": "paragraph", "role": "aside", "hidden": True, "text": "_The Founder of the Family_"},
        {"type": "list_item", "role": "genealogy", "text": "8. JOHANN AMBROSIUS, 1645-1695."},
        {"type": "list_item", "role": "genealogy", "text": "9. JOHANN CHRISTOPH, 1645-1693."},
        {"type": "paragraph", "text": "Bach was born at Eisenach."},
    ]
    md = translation_source_from_blocks(blocks)
    assert "[Sidenote:" not in md
    assert "_The Founder of the Family_" not in md
    assert "8. JOHANN AMBROSIUS, 1645-1695." in md
    assert "9. JOHANN CHRISTOPH, 1645-1693." in md
    eight, nine = md.split("9. JOHANN CHRISTOPH", 1)
    assert "8. JOHANN AMBROSIUS" in eight
    assert "9." not in eight


def test_chapters_for_translation_uses_parsed_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_corpus(tmp_path, monkeypatch, parsed=True)
    rows = chapters_for_translation(WORK, corpus=tmp_path)
    assert [row["source_kind"] for row in rows] == ["parsed", "parsed"]
    first = rows[0]["text"]
    assert "[Sidenote:" not in first
    assert "_The Founder of the Family_" not in first
    assert "8. JOHANN AMBROSIUS, 1645-1695." in first
    assert "9. JOHANN CHRISTOPH, 1645-1693." in first
    assert "8. JOHANN AMBROSIUS, 1645-1695. 9." not in first
    assert rows[0]["blocks"][1]["hidden"] is True


def test_chapters_for_translation_falls_back_to_raw_slice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_corpus(tmp_path, monkeypatch, parsed=False)
    rows = chapters_for_translation(WORK, corpus=tmp_path)
    assert rows[0]["source_kind"] == "raw_slice"
    assert "[Sidenote: _The Founder of the Family_]" in rows[0]["text"]


def test_init_uses_parsed_chapter_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_corpus(tmp_path, monkeypatch, parsed=True)
    result = init_translation_project(WORK, translation_mode="normal")
    assert result["project"]["chapter_source"] == "ref"
    assert result["project"]["source_text_kind"] == "parsed"
    chi = json.loads((tmp_path / "translations" / WORK / "segments/chchapteri.json").read_text(encoding="utf-8"))
    assert chi["source_text_kind"] == "parsed"
    assert "[Sidenote:" not in chi["source_text"]
    assert any(b.get("role") == "genealogy" for b in chi["ref_blocks"])
    assert any(b.get("hidden") for b in chi["ref_blocks"])


def test_sync_reparses_existing_slices_without_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_corpus(tmp_path, monkeypatch, parsed=False)
    shutil.rmtree(tmp_path / "read-editions")
    init_translation_project(WORK, translation_mode="normal")
    seg_dir = tmp_path / "translations" / WORK / "segments"
    chi_path = next(p for p in sorted(seg_dir.glob("ch*.json")) if "-sample" not in p.name)
    before = json.loads(chi_path.read_text(encoding="utf-8"))
    assert "[Sidenote:" in before["source_text"]
    result = sync_translation_chapters_from_ref(WORK, overwrite=True, keep_approved=True)
    assert result["via"] == "reparse_existing"
    after = json.loads(chi_path.read_text(encoding="utf-8"))
    assert after["source_text_kind"] == "parsed"
    assert "[Sidenote:" not in after["source_text"]
    assert any(b.get("hidden") for b in after["ref_blocks"])


def test_sync_keeps_approved_and_rewrites_the_rest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_corpus(tmp_path, monkeypatch, parsed=True)
    init_translation_project(WORK, translation_mode="normal")
    chi_path = tmp_path / "translations" / WORK / "segments/chchapteri.json"
    chii_path = tmp_path / "translations" / WORK / "segments/chchapterii.json"
    chi = json.loads(chi_path.read_text(encoding="utf-8"))
    chi["final"] = "Bản đã duyệt."
    chi["status"] = "approved"
    chi_path.write_text(json.dumps(chi, ensure_ascii=False), encoding="utf-8")
    chii = json.loads(chii_path.read_text(encoding="utf-8"))
    chii["final"] = "Bản nháp cũ."
    chii["status"] = "draft_ready"
    chii_path.write_text(json.dumps(chii, ensure_ascii=False), encoding="utf-8")

    pkg = tmp_path / "read-editions" / WORK / HASH / "chapters/sec-002.json"
    doc = json.loads(pkg.read_text(encoding="utf-8"))
    doc["blocks"][-1]["text"] = "Bach went to Weimar after the parsed matcher ran."
    pkg.write_text(json.dumps(doc), encoding="utf-8")

    result = sync_translation_chapters_from_ref(WORK, overwrite=True, keep_approved=True)
    assert result["source_text_kind"] == "parsed"
    assert "chchapteri" in result["kept_approved"]
    assert "chchapterii" in result["rewritten"]

    kept = json.loads(chi_path.read_text(encoding="utf-8"))
    assert kept["final"] == "Bản đã duyệt."
    assert kept["status"] == "approved"
    rewritten = json.loads(chii_path.read_text(encoding="utf-8"))
    assert rewritten["final"] is None
    assert rewritten["status"] == "pending"
    assert "parsed matcher ran" in rewritten["source_text"]
    assert rewritten["title_vi"] == chii["title_vi"]

