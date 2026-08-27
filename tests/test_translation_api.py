from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from knowledgehub.server import create_app
from knowledgehub.translation.project import init_translation_project, select_translation_mode


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    init_translation_project("grotius--freedom_of_the_seas")
    sample = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Bản dịch tight."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode("grotius--freedom_of_the_seas", "tight")
    chi = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    chi_payload = json.loads(chi.read_text(encoding="utf-8"))
    chi_payload["qa"] = {
        "scores": {"fidelity": 8, "fluency": 9, "terminology": 8, "completeness": 10, "overall": 8},
        "summary_vi": "Tốt.",
        "issues": [],
    }
    chi.write_text(json.dumps(chi_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ann = tmp_path / "translations/grotius--freedom_of_the_seas/annotations.json"
    ann.write_text(
        json.dumps(
            {
                "annotations": [
                    {
                        "id": "grotius--freedom_of_the_seas--chi--fn-1",
                        "chapter": "I",
                        "kind": "footnote",
                        "marker": "[1]",
                        "title_vi": "Chú thích [1]",
                        "body_vi": "Pliny.",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return TestClient(create_app())


def test_translation_list_and_project(client: TestClient):
    listed = client.get("/api/translations").json()
    assert listed["total"] == 1
    assert listed["projects"][0]["source_work_id"] == "grotius--freedom_of_the_seas"
    project = client.get("/api/translations/grotius--freedom_of_the_seas").json()
    assert project["project"]["translation_mode"] == "tight"
    assert len(project["chapters"]) == 2
    ch_i = next(c for c in project["chapters"] if c["chapter"] == "I")
    assert ch_i["qa_overall"] == 8
    assert ch_i["has_final"] is True


def test_translation_segment_and_annotations(client: TestClient):
    seg = client.get("/api/translations/grotius--freedom_of_the_seas/segments/I").json()
    assert seg["translation"] == "Bản dịch tight."
    assert seg["qa"]["scores"]["overall"] == 8
    ann = client.get("/api/translations/grotius--freedom_of_the_seas/annotations?chapter=I").json()
    assert ann["total"] == 1
    assert ann["annotations"][0]["marker"] == "[1]"


def test_translation_page_route(client: TestClient):
    page = client.get("/translation/grotius--freedom_of_the_seas/I")
    assert page.status_code == 200
    assert "Dịch thuật" in page.text


def test_translation_qa_endpoint(client: TestClient):
    qa_json = json.dumps(
        {
            "scores": {
                "fidelity": 9,
                "fluency": 9,
                "terminology": 9,
                "completeness": 10,
                "overall": 9,
            },
            "summary_vi": "Rất tốt.",
            "issues": [],
        }
    )
    with patch("knowledgehub.translation.api.qa_segment") as mock_qa:
        mock_qa.return_value = {"scores": {"overall": 9}, "summary_vi": "Rất tốt."}
        res = client.post("/api/translations/grotius--freedom_of_the_seas/qa/I")
    assert res.status_code == 200
    mock_qa.assert_called_once_with("grotius--freedom_of_the_seas", "I")
