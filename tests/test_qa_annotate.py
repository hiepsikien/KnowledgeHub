from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from knowledgehub.translation.annotate import annotate_segment
from knowledgehub.translation.llm_json import parse_json_object
from knowledgehub.translation.project import init_translation_project, select_translation_mode
from knowledgehub.translation.qa import qa_segment


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


def _lock_tight(corpus: Path) -> None:
    init_translation_project("grotius--freedom_of_the_seas")
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode("grotius--freedom_of_the_seas", "tight")


def test_parse_json_object_strips_fences():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_qa_segment_writes_scores(corpus: Path):
    _lock_tight(corpus)
    qa_json = json.dumps(
        {
            "scores": {
                "fidelity": 9,
                "fluency": 8,
                "terminology": 9,
                "completeness": 10,
                "overall": 9,
            },
            "summary_vi": "Bản dịch sát nghĩa, thuật ngữ nhất quán.",
            "issues": [],
        }
    )
    with patch("knowledgehub.translation.qa.deepseek_chat", return_value=qa_json):
        result = qa_segment("grotius--freedom_of_the_seas", "I")
    assert result["scores"]["overall"] == 9
    chi = json.loads((corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json").read_text())
    assert chi["qa"]["mode"] == "tight"
    assert chi["qa"]["scores"]["fidelity"] == 9


def test_annotate_segment_merges_annotations(corpus: Path):
    _lock_tight(corpus)
    ann_json = json.dumps(
        {
            "annotations": [
                {
                    "id": "grotius--freedom_of_the_seas--chi--fn-1",
                    "marker": "[1]",
                    "kind": "footnote",
                    "anchor_text": "Pliny",
                    "title_vi": "Chú thích [1]",
                    "body_vi": "Pliny the Elder, nhà sử gia La Mã.",
                }
            ]
        }
    )
    with patch("knowledgehub.translation.annotate.gemini_generate", return_value=ann_json):
        result = annotate_segment("grotius--freedom_of_the_seas", "I")
    assert result["added_or_updated"] == 1
    store = json.loads((corpus / "translations/grotius--freedom_of_the_seas/annotations.json").read_text())
    assert len(store["annotations"]) == 1
    assert store["annotations"][0]["body_vi"].startswith("Pliny")


def test_qa_requires_locked_mode(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    with pytest.raises(ValueError, match="translation_mode not locked"):
        qa_segment("grotius--freedom_of_the_seas", "I")
