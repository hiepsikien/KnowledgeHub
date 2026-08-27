from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledgehub.translation.fetch import fetch_grotius_freedom_of_seas
from knowledgehub.translation.project import init_translation_project


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
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    assert sample.is_file()
    payload = json.loads(sample.read_text(encoding="utf-8"))
    assert payload["chapter"] == "I"
    assert "English paragraph one" in payload["source_text"]


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
