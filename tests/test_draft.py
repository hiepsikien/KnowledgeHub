from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from knowledgehub.translation.draft import draft_sample
from knowledgehub.translation.project import init_translation_project
from knowledgehub.translation.providers import ProviderError, deepseek_chat


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
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(json.dumps([{"id": "grotius", "name": "Grotius"}]), encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(tmp_path))
    return tmp_path


def test_deepseek_missing_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="DEEPSEEK_API_KEY"):
        deepseek_chat([{"role": "user", "content": "hi"}])


def test_draft_sample_writes_normal(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    with (
        patch("knowledgehub.translation.draft.deepseek_chat", return_value="Bản dịch thô."),
        patch("knowledgehub.translation.draft.gemini_generate", return_value="Bản dịch đã chỉnh."),
    ):
        result = draft_sample("grotius--freedom_of_the_seas", mode="normal")
    assert result["mode"] == "normal"
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    assert payload["drafts"]["normal"] == "Bản dịch đã chỉnh."
    assert payload["draft_raw"]["normal"] == "Bản dịch thô."
    assert payload["final"] == "Bản dịch đã chỉnh."
    project = json.loads((corpus / "translations/grotius--freedom_of_the_seas/project.json").read_text())
    assert project["translation_mode"] is None
    assert project["status"] == "sample_ready"
