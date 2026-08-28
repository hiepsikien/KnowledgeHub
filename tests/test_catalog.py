from __future__ import annotations

import json
from pathlib import Path

from knowledgehub.catalog import build_catalog, work_id
from knowledgehub.read_publish import PublishError, prepare_publish
from knowledgehub.validate import validate_catalog


def _mini_corpus(tmp: Path) -> Path:
    corpus = tmp / "corpus"
    src = corpus / "sources" / "locke"
    src.mkdir(parents=True)
    (src / "raw").mkdir()
    (src / "raw" / "second_treatise.txt").write_text("Of civil government.\n" * 20, encoding="utf-8")
    (src / "works.json").write_text(
        json.dumps(
            [
                {
                    "file": "second_treatise.txt",
                    "work": "Second Treatise of Government",
                    "year": 1689,
                    "license": "public_domain_usa_gutenberg",
                    "source_url": "https://www.gutenberg.org/ebooks/7370",
                    "concepts": ["property"],
                }
            ]
        ),
        encoding="utf-8",
    )
    (corpus / "licenses.json").write_text(
        (Path(__file__).resolve().parents[1] / "corpus" / "licenses.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return corpus


def test_work_id_stable():
    assert work_id("locke", "second_treatise.txt") == "locke--second_treatise"


def test_build_validate_and_publish_gate(tmp_path):
    corpus = _mini_corpus(tmp_path)
    stats = build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    assert stats == {"authors": 1, "works": 1}
    assert validate_catalog(corpus=corpus) == []
    wid = "locke--second_treatise"
    try:
        prepare_publish(wid, corpus=corpus)
        raise AssertionError("blocked works must not publish")
    except PublishError:
        pass
    from knowledgehub.catalog import set_read_consumer

    set_read_consumer(wid, True, corpus=corpus)
    payload = prepare_publish(wid, corpus=corpus)
    assert payload["hub_work_id"] == wid
    assert payload["raw_text"].startswith("Of civil government")
    assert payload["hub_content_hash"]
    assert "glossary" not in payload
