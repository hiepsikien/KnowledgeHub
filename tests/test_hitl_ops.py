from __future__ import annotations

from pathlib import Path

from knowledgehub.edition.hitl_ops import scan_footnotes, scan_quotes, scan_wrap

CORPUS = Path(__file__).resolve().parent / "fixtures" / "ref_corpus"
GROTIUS = (CORPUS / "en" / "grotius_treatise_ch1.txt").read_text(encoding="utf-8")
HUME = (CORPUS / "en" / "hume_treatise.txt").read_text(encoding="utf-8")


def test_wrap_flags_spurious_blank_before_athenians():
    items, extra = scan_wrap(GROTIUS, chapter_id="ch1", family="gutenberg")
    assert extra["auto_join"] >= 1
    hit = next(
        (
            row
            for row in items
            if "Megarians" in row["prev"] and "Athenians" in row["next"]
        ),
        None,
    )
    assert hit is not None
    assert hit["proposed"] == "join"
    assert hit["suspect"] is True
    assert "blank_line" in hit["reasons"]


def test_footnotes_unmatched_markers_on_grotius_chapter():
    items, extra = scan_footnotes(GROTIUS, chapter_id="ch1", book_text=GROTIUS)
    markers = {row["marker"] for row in items}
    assert "[1]" in markers
    assert "[12]" in markers
    assert extra["unmatched"] >= 1
    unmatched = [row for row in items if row["status"] == "unmatched_marker"]
    assert unmatched
    assert all(row["suspect"] for row in unmatched)


def test_footnotes_link_indented_hume_note():
    items, _extra = scan_footnotes(HUME, chapter_id="ch1", book_text=HUME)
    one = next(row for row in items if row["marker"] == "[1]")
    assert one["status"] == "linked"
    assert "impression and idea" in one["body"]
    assert one["body_source"] == "indented"


def test_footnotes_link_dump_from_book_tail():
    body = GROTIUS + "\n\nFOOTNOTES:\n\n[1] Pliny, Natural History.\n\n[4] Seneca, Natural Questions.\n"
    items, extra = scan_footnotes(GROTIUS, chapter_id="ch1", book_text=body)
    one = next(row for row in items if row["marker"] == "[1]")
    four = next(row for row in items if row["marker"] == "[4]")
    assert one["status"] == "linked"
    assert "Pliny" in one["body"]
    assert four["status"] == "linked"
    assert extra["linked"] >= 2


def test_quotes_find_vergil_blockquote_and_emphasis():
    items, _extra = scan_quotes(GROTIUS, chapter_id="ch1", family="gutenberg", work_id="grotius--freedom_of_the_seas")
    marks = {row["mark"] for row in items}
    assert "blockquote" in marks
    assert "em" in marks
    texts = " ".join(row["text"] for row in items)
    assert "Not every plant" in texts or "cruel seas" in texts


def _grotius_corpus(tmp: Path) -> Path:
    import json

    corpus = tmp / "corpus"
    src = corpus / "sources" / "grotius"
    src.mkdir(parents=True)
    (src / "raw").mkdir()
    notes = "\n\nFOOTNOTES:\n\n[1] Pliny, Natural History, book two.\n\n[4] Seneca, Natural Questions.\n"
    (src / "raw" / "freedom_of_the_seas.txt").write_text(GROTIUS + notes, encoding="utf-8")
    (src / "works.json").write_text(
        json.dumps(
            [
                {
                    "file": "freedom_of_the_seas.txt",
                    "work": "The Freedom of the Seas",
                    "year": 1609,
                    "license": "public_domain_usa_gutenberg",
                    "source_url": "https://www.gutenberg.org/ebooks/1022",
                    "concepts": ["law"],
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


def test_hitl_trial_then_book_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from knowledgehub.catalog import build_catalog
    from knowledgehub.hash import refresh_hashes
    from knowledgehub.server import create_app

    corpus = _grotius_corpus(tmp_path)
    build_catalog(src=corpus / "sources", dest=corpus / "catalog")
    refresh_hashes(corpus=corpus)
    monkeypatch.setenv("KNOWLEDGEHUB_CORPUS", str(corpus))
    monkeypatch.delenv("KNOWLEDGEHUB_OPS_SECRET", raising=False)
    monkeypatch.setenv("KNOWLEDGEHUB_JOB_WORKER", "0")
    monkeypatch.setenv("KNOWLEDGEHUB_REF_LLM_DEFAULT", "0")
    client = TestClient(create_app())
    wid = "grotius--freedom_of_the_seas"

    macro = client.post(f"/api/works/{wid}/read-edition/macro", json={"use_llm": False})
    assert macro.status_code == 200, macro.text
    chapters = client.get(f"/api/works/{wid}/read-edition/manifest").json()["manifest"]["chapters"]
    ch_id = chapters[0]["chapter_id"]

    blocked = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/scan",
        json={"scope": "book", "chapter_id": ch_id},
    )
    assert blocked.status_code == 400

    trial = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/scan",
        json={"scope": "chapter", "chapter_id": ch_id},
    )
    assert trial.status_code == 200, trial.text
    wrap = trial.json()
    assert wrap["status"] == "trial"
    assert wrap["trial_chapter_id"] == ch_id
    assert wrap["summary"]["auto_join"] >= 1
    suspects = [row for row in wrap["items"] if row["suspect"]]
    if suspects:
        decided = client.post(
            f"/api/works/{wid}/read-edition/hitl/wrap/decide",
            json={"decision": "accept", "item_ids": [suspects[0]["id"]]},
        )
        assert decided.status_code == 200
        assert any(row.get("decision") == "accept" for row in decided.json()["items"])

    confirm = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/confirm",
        json={"chapter_id": ch_id},
    )
    assert confirm.status_code == 200
    assert confirm.json()["trial_confirmed"] is True

    book = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/scan",
        json={"scope": "book"},
    )
    assert book.status_code == 200
    assert book.json()["scope"] == "book"

    notes = client.post(
        f"/api/works/{wid}/read-edition/hitl/footnotes/scan",
        json={"scope": "chapter", "chapter_id": ch_id},
    )
    assert notes.status_code == 200
    payload = notes.json()
    markers = {row["marker"] for row in payload["items"]}
    assert "[1]" in markers
    linked = next(row for row in payload["items"] if row["marker"] == "[1]")
    assert linked["status"] == "linked"
    assert "Pliny" in linked["body"]

    quotes = client.post(
        f"/api/works/{wid}/read-edition/hitl/quotes/scan",
        json={"scope": "chapter", "chapter_id": ch_id},
    )
    assert quotes.status_code == 200
    marks = {row["mark"] for row in quotes.json()["items"]}
    assert "em" in marks or "blockquote" in marks

    overview = client.get(f"/api/works/{wid}/read-edition/hitl")
    assert overview.status_code == 200
    kinds = overview.json()["kinds"]
    assert kinds["wrap"]["trial_confirmed"] is True
    assert kinds["footnotes"]["status"] == "trial"
