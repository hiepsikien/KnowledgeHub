from __future__ import annotations

import json
from pathlib import Path

from knowledgehub.catalog import build_catalog, set_read_consumer, upsert_work
from knowledgehub.read_publish import prepare_publish
from knowledgehub.translation.assemble import IncompleteTranslation, assemble_finals
from knowledgehub.translation.project import init_translation_project, select_translation_mode
from knowledgehub.translation.promote import promote_translation
from knowledgehub.validate import validate_catalog
from test_catalog import _mini_corpus


def _fill_finals(corpus: Path, source_id: str = "grotius--freedom_of_the_seas") -> None:
    for stem, text in (("chi", "Chương một."), ("chii", "Chương hai.")):
        path = corpus / "translations" / source_id / "segments" / f"{stem}.json"
        row = json.loads(path.read_text(encoding="utf-8"))
        row["final"] = text
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _translation_corpus(tmp_path: Path, monkeypatch) -> Path:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sources = tmp_path / "sources/grotius/raw"
    sources.mkdir(parents=True)
    (sources / "freedom_of_the_seas.txt").write_text(
        "CHAPTER I\n\n" + ("English paragraph one. " * 40) + "\n\nCHAPTER II\n\n" + ("English paragraph two. " * 40),
        encoding="utf-8",
    )
    (tmp_path / "licenses.json").write_text(
        (Path(__file__).resolve().parents[1] / "corpus" / "licenses.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    works = [
        {
            "id": "grotius--freedom_of_the_seas",
            "title": "The Freedom of the Seas",
            "author_id": "grotius",
            "language": "en",
            "license": "public_domain_usa_gutenberg",
            "content_file": "sources/grotius/raw/freedom_of_the_seas.txt",
            "year": 1609,
            "translator": "Ralph Van Deman Magoffin",
            "content_hash": "abc",
            "rights": {"basis": "public_domain", "consumers": {"think": "allowed", "read": "allowed"}},
            "read": {"category_slug": "essays", "price_cents": 0, "split_length": "standard"},
        }
    ]
    (catalog / "works.json").write_text(json.dumps(works), encoding="utf-8")
    (catalog / "authors.json").write_text(
        json.dumps([{"id": "grotius", "name": "Grotius", "display_name": "Hugo Grotius"}]),
        encoding="utf-8",
    )
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(tmp_path))
    init_translation_project("grotius--freedom_of_the_seas")
    sample = tmp_path / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["drafts"]["tight"] = "Chương một."
    sample.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    select_translation_mode("grotius--freedom_of_the_seas", "tight")
    return tmp_path


def test_assemble_requires_every_chapter_final(tmp_path, monkeypatch):
    corpus = _translation_corpus(tmp_path, monkeypatch)
    try:
        assemble_finals("grotius--freedom_of_the_seas")
        raise AssertionError("incomplete translation must not assemble")
    except IncompleteTranslation as exc:
        assert "II" in exc.missing
    _fill_finals(corpus)
    text, meta = assemble_finals("grotius--freedom_of_the_seas")
    assert "Chương một." in text
    assert "Chương hai." in text
    assert meta["chapters"] == 2


def test_promote_and_publish_vietnamese(tmp_path, monkeypatch):
    corpus = _translation_corpus(tmp_path, monkeypatch)
    _fill_finals(corpus)
    ann = corpus / "translations/grotius--freedom_of_the_seas/annotations.json"
    ann.write_text(
        json.dumps(
            {
                "annotations": [
                    {
                        "kind": "footnote",
                        "marker": "[17]",
                        "anchor_text": "Gordian",
                        "body_vi": "Hoàng đế Gordian III.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = promote_translation("grotius--freedom_of_the_seas")
    work = result["work"]
    assert work["id"] == "grotius--freedom_of_the_seas_vi"
    assert work["language"] == "vi"
    assert work["derived_from"] == "grotius--freedom_of_the_seas"
    assert work["origin"] == "hub_translation"
    assert work["license"] == "hub_editorial_vi"
    assert work["content_file"] is None
    assert work["content_hash"]
    assert validate_catalog(corpus=corpus) == []
    set_read_consumer(work["id"], True, corpus=corpus)
    from read_edition_helpers import bootstrap_read_edition

    bootstrap_read_edition(work["id"], corpus=corpus)
    payload = prepare_publish(work["id"], corpus=corpus)
    assert payload["hub_work_id"] == "grotius--freedom_of_the_seas_vi"
    assert payload["language"] == "vi"
    assert payload["raw_text"].startswith("Chương một.")
    assert payload["glossary"][0]["aliases"] == ["[17]"]
    assert payload["glossary"][0]["name"] == "Gordian [17]"
    assert payload["notes"][0]["label"] == "Gordian [17]"
    assert payload["notes"][0]["marker"] == "[17]"
    assert payload["credits"] == {
        "author_name": "Hugo Grotius",
        "author_hub_id": "grotius",
        "translator_name": "Knowledge Hub",
        "translator_role": "hub_editorial",
        "source": {
            "hub_work_id": "grotius--freedom_of_the_seas",
            "title": "The Freedom of the Seas",
            "year": 1609,
            "language": "en",
        },
    }
    bootstrap_read_edition("grotius--freedom_of_the_seas", corpus=corpus)
    english = prepare_publish("grotius--freedom_of_the_seas", corpus=corpus)
    assert "glossary" not in english
    assert "Chương một." not in english["raw_text"]
    assert english["credits"]["author_name"] == "Hugo Grotius"
    assert english["credits"]["author_hub_id"] == "grotius"
    assert english["credits"]["translator_name"] == "Ralph Van Deman Magoffin"
    assert english["credits"]["translator_role"] == "translator"
    assert english["credits"]["source"] is None


def test_build_catalog_keeps_promoted_translation(tmp_path):
    corpus = _mini_corpus(tmp_path)
    build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    upsert_work(
        {
            "id": "locke--second_treatise_vi",
            "title": "Khảo luận hai (Tiếng Việt)",
            "author_id": "locke",
            "language": "vi",
            "license": "hub_editorial_vi",
            "origin": "hub_translation",
            "derived_from": "locke--second_treatise",
            "content_file": None,
            "content_hash": "x",
            "rights": {"basis": "editorial_derivative", "consumers": {"think": "blocked", "read": "blocked"}},
        },
        corpus=corpus,
    )
    stats = build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    assert stats["works"] == 2
    assert validate_catalog(corpus=corpus) == []
