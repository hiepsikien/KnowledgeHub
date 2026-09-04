from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledgehub.translation.assemble import chapter_sort_key
from knowledgehub.translation.fetch import fetch_grotius_freedom_of_seas
from knowledgehub.translation.project import init_translation_project, select_translation_mode
from knowledgehub.translation.segment import split_chapters
from knowledgehub.translation.titles import fallback_title_vi, translate_chapter_titles


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
    chi = json.loads((corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json").read_text())
    assert chi["title_vi"] == "Chương 1"


def test_init_locks_mode_without_sample(corpus: Path):
    result = init_translation_project("grotius--freedom_of_the_seas", translation_mode="normal")
    assert result["project"]["translation_mode"] == "normal"
    assert result["project"]["status"] == "mode_locked"
    assert result["project"]["chapter_source"] == "split"
    assert "sample" not in result["paths"]
    sample = corpus / "translations/grotius--freedom_of_the_seas/segments/chi-sample.json"
    assert not sample.exists()
    project = json.loads((corpus / "translations/grotius--freedom_of_the_seas/project.json").read_text())
    assert "sample_segment" not in project


def test_init_does_not_split_with_llm_and_survives_title_timeout(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    def boom_gemini(*_args, **_kwargs):
        raise AssertionError("creating a translation project must not split with Gemini")

    from knowledgehub.translation import titles as titles_mod
    from knowledgehub.translation.providers import ProviderError

    real_translate = titles_mod.translate_chapter_titles

    def translate_force(titles, *, model=None, use_llm=None):
        if use_llm is False:
            return real_translate(titles, model=model, use_llm=False)
        root = corpus / "translations/grotius--freedom_of_the_seas"
        assert (root / "project.json").is_file()
        assert (root / "segments/chi.json").is_file()
        return real_translate(titles, model=model, use_llm=True)

    def boom_prompt(*_args, **_kwargs):
        raise ProviderError("timeout")

    monkeypatch.setattr("knowledgehub.translation.providers.gemini_generate", boom_gemini)
    monkeypatch.setattr("knowledgehub.translation.titles.translate_chapter_titles", translate_force)
    monkeypatch.setattr("knowledgehub.translation.titles.complete_prompt", boom_prompt)
    result = init_translation_project("grotius--freedom_of_the_seas", translation_mode="normal")
    assert result["project"]["source"]["chapters"] == 2
    chi = json.loads(
        (corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json").read_text(encoding="utf-8")
    )
    assert chi["title_vi"] == "Chương 1"
    assert "English paragraph one" in chi["source_text"]


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


def test_init_recreates_incomplete_project_dir(corpus: Path):
    leftover = corpus / "translations/grotius--freedom_of_the_seas"
    (leftover / "segments").mkdir(parents=True)
    (leftover / "segments/stale.json").write_text("{}", encoding="utf-8")
    assert not (leftover / "project.json").is_file()
    result = init_translation_project("grotius--freedom_of_the_seas", translation_mode="normal")
    assert result["project"]["translation_mode"] == "normal"
    assert result["project"]["source"]["chapters"] == 2
    assert (leftover / "project.json").is_file()
    assert (leftover / "segments/chi.json").is_file()
    assert not (leftover / "segments/stale.json").is_file()


def test_init_recreates_project_json_without_chapters(corpus: Path):
    leftover = corpus / "translations/grotius--freedom_of_the_seas"
    leftover.mkdir(parents=True)
    (leftover / "project.json").write_text('{"source_work_id": "grotius--freedom_of_the_seas"}\n', encoding="utf-8")
    (leftover / "segments").mkdir()
    result = init_translation_project("grotius--freedom_of_the_seas", translation_mode="normal")
    assert result["project"]["source"]["chapters"] == 2
    assert (leftover / "segments/chi.json").is_file()


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
    assert chapter_sort_key("ChapterV") < chapter_sort_key("ChapterIX")
    assert chapter_sort_key("ChapterIX") < chapter_sort_key("ChapterX")
    assert chapter_sort_key("preface") < chapter_sort_key("ChapterI")
    assert chapter_sort_key("ChapterXIV") < chapter_sort_key("CatalogueofBachs")
    assert chapter_sort_key("ChapterXIX") < chapter_sort_key("ChapterXX")


def test_segment_files_follow_ref_structure_order(corpus: Path):
    from knowledgehub.translation.assemble import segment_files

    work = "arnold--essays"
    seg_dir = corpus / "translations" / work / "segments"
    seg_dir.mkdir(parents=True)
    rows = [
        ("chiiimauricedeguri", "IIIMAURICEDEGURI", "sec-003"),
        ("chiitheliteraryinf", "IITHELITERARYINF", "sec-002"),
        ("chithefunctionofcr", "ITHEFUNCTIONOFCR", "sec-001"),
    ]
    for stem, chapter, ref_id in rows:
        (seg_dir / f"{stem}.json").write_text(
            json.dumps(
                {
                    "chapter": chapter,
                    "source_text": "body",
                    "ref_chapter_id": ref_id,
                }
            ),
            encoding="utf-8",
        )
    assert [p.stem for p in segment_files(work)] == [
        "chithefunctionofcr",
        "chiitheliteraryinf",
        "chiiimauricedeguri",
    ]


def test_fallback_title_vi_is_vietnamese():
    assert fallback_title_vi("Chapter I") == "Chương 1"
    assert fallback_title_vi("ChapterI") == "Chương 1"
    assert fallback_title_vi("CHAPTER XIV") == "Chương 14"
    assert fallback_title_vi("I") == "Chương 1"
    assert fallback_title_vi("Preface") == "Lời nói đầu"
    assert fallback_title_vi("Bibliography") == "Thư mục"
    assert fallback_title_vi("Glossary") == "Bảng chú giải"
    assert fallback_title_vi("Catalogue of Bach’s Vocal Works").startswith("Mục lục")


def test_translate_titles_uses_llm(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "knowledgehub.translation.titles.complete_prompt",
        lambda *_args, **_kwargs: '{"titles": ["Chương 1", "Lời nói đầu"]}',
    )
    assert translate_chapter_titles(["Chapter I", "Preface"], use_llm=True) == [
        "Chương 1",
        "Lời nói đầu",
    ]


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
