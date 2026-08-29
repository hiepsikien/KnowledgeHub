from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledgehub.translation.assemble import chapter_sort_key
from knowledgehub.translation.fetch import fetch_grotius_freedom_of_seas
from knowledgehub.translation.project import init_translation_project, select_translation_mode
from knowledgehub.translation.segment import split_chapters


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sources = tmp_path / "sources/grotius/raw"
    sources.mkdir(parents=True)
    (sources / "freedom_of_the_seas.txt").write_text(
        "CHAPTER I\n\nEnglish paragraph one.\n\nCHAPTER II\n\nEnglish paragraph two.\n",
        encoding="utf-8",
    )
    works = [
        {
            "id": "grotius--freedom_of_the_seas",
            "title": "The Freedom of the Seas",
            "author_id": "grotius",
            "language": "en",
            "content_file": "sources/grotius/raw/freedom_of_the_seas.txt",
            "gutenberg_id": "75962",
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(json.dumps([{"id": "grotius", "name": "Grotius"}]), encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(tmp_path))
    return tmp_path


def test_init_translation_project(corpus: Path):
    result = init_translation_project("grotius--freedom_of_the_seas")
    assert result["project"]["source"]["chapters"] == 2
    assert result["project"]["translation_work_id"] == "grotius--freedom_of_the_seas_vi"
    assert result["project"]["translation_mode"] is None
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    assert sample.is_file()
    payload = json.loads(sample.read_text(encoding="utf-8"))
    assert payload["chapter"] == "I"
    assert "English paragraph one" in payload["source_text"]


def test_init_locks_mode_without_sample(corpus: Path):
    result = init_translation_project("grotius--freedom_of_the_seas", translation_mode="normal")
    assert result["project"]["translation_mode"] == "normal"
    assert result["project"]["status"] == "mode_locked"
    assert "sample" not in result["paths"]
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    assert not sample.exists()
    project = json.loads((corpus / "translations/grotius--freedom_of_the_seas/project.json").read_text())
    assert "sample_segment" not in project


def test_select_mode_without_sample_draft(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    result = select_translation_mode("grotius--freedom_of_the_seas", "loose")
    assert result["translation_mode"] == "loose"
    project = json.loads((corpus / "translations/grotius--freedom_of_the_seas/project.json").read_text())
    assert project["status"] == "mode_locked"
    chi = json.loads((corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json").read_text())
    assert not chi.get("final")


def test_select_translation_mode(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = select_translation_mode("grotius--freedom_of_the_seas", "tight")
    assert result["translation_mode"] == "tight"
    project = json.loads((corpus / "translations/grotius--freedom_of_the_seas/project.json").read_text())
    assert project["translation_mode"] == "tight"
    assert project["status"] == "mode_locked"
    chi = json.loads((corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json").read_text())
    assert chi["final"] == "Bản dịch tight."


def test_overwrite_rewrites_chapter_source(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    chi = corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["source_text"] = "STALE"
    chi.write_text(json.dumps(payload), encoding="utf-8")
    init_translation_project("grotius--freedom_of_the_seas", overwrite=True)
    rewritten = json.loads(chi.read_text(encoding="utf-8"))
    assert "STALE" not in rewritten["source_text"]
    assert "English paragraph one" in rewritten["source_text"]


def test_split_arabic_and_plain_text():
    arabic = split_chapters("Chapter 1\n\nFirst.\n\nChapter 2\n\nSecond.\n")
    assert [row["chapter"] for row in arabic] == ["1", "2"]
    assert "First." in arabic[0]["text"]
    plain = split_chapters("Of civil government.\n" * 8)
    assert len(plain) == 1
    assert plain[0]["chapter"] == "1"
    assert chapter_sort_key("2") < chapter_sort_key("10")
    assert chapter_sort_key("preface") < chapter_sort_key("I")


def test_fetch_grotius_writes_english_raw(corpus: Path, monkeypatch: pytest.MonkeyPatch):
    sample = Path(__file__).parent / "fixtures/grotius_pg_snippet.txt"
    monkeypatch.setattr(
        "knowledgehub.translation.fetch.urllib.request.urlopen",
        lambda *a, **k: type("R", (), {"read": lambda self: sample.read_bytes(), "__enter__": lambda s: s, "__exit__": lambda *x: None})(),
    )
    out = fetch_grotius_freedom_of_seas()
    raw = corpus / "sources/grotius/raw/freedom_of_the_seas.txt"
    text = raw.read_text(encoding="utf-8")
    assert "Hoc igitur" not in text
    assert out["fetch"]["chapters"] >= 1
