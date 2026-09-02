from __future__ import annotations

from pathlib import Path

from knowledgehub.edition.hitl_ops import (
    apply_quote_decisions,
    apply_wrap_overrides,
    extract_dump_notes,
    footnote_records_from_items,
    scan_footnotes,
    scan_quotes,
    scan_wrap,
    summarize_items,
    wrap_overrides_from_items,
)

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
    body = GROTIUS + "\n\nFOOTNOTES:\n\n[1] Pliny, Natural History.\n\n[4] Seneca, Natural Questions.\n\n[99] Only in the dump.\n"
    items, extra = scan_footnotes(GROTIUS, chapter_id="ch1", book_text=body)
    one = next(row for row in items if row["marker"] == "[1]")
    four = next(row for row in items if row["marker"] == "[4]")
    assert one["status"] == "linked"
    assert one["suspect"] is True
    assert "footnotes_dump_global" in one["reasons"]
    assert "Pliny" in one["body"]
    assert four["status"] == "linked"
    assert four["suspect"] is True
    assert extra["linked"] >= 2
    assert all(row["number"] != 99 for row in items)
    auto = footnote_records_from_items(items, chapter_id="ch1")
    assert all(row.get("number") not in {1, 4} for row in auto)
    one["decision"] = "accept"
    accepted = footnote_records_from_items(items, chapter_id="ch1")
    assert any(row.get("number") == 1 for row in accepted)


BERGSON_PG_NOTES = """\
CHAPTER I

THE EVOLUTION OF LIFE

True, biologists are not agreed on what is gained and what is lost
between the day of birth and the day of death.[5] More probable is the
theory of residual substances which finally "crust it over."[6] Must we
declare any explanation insufficient that does not take account of
phagocytosis?[7]

FOOTNOTES:

[Footnote 5: There are those who hold to the continual growth in the
volume of protoplasm from the birth of the cell right on to its death.]

[Footnote 6: Le Dantec, _L'Individualité et l'erreur individualiste_,
Paris, 1905, pp. 84 ff.]

[Footnote 7: Metchnikoff, _La Dégénérescence sénile_.]
"""


def test_footnotes_link_gutenberg_bracket_dump_in_chapter():
    items, extra = scan_footnotes(BERGSON_PG_NOTES, chapter_id="ch1", dump_notes={})
    by_marker = {row["marker"]: row for row in items}
    assert extra["linked"] == 3
    assert extra["unmatched"] == 0
    five = by_marker["[5]"]
    assert five["status"] == "linked"
    assert five["suspect"] is False
    assert "footnotes_dump_global" not in five["reasons"]
    assert "volume of protoplasm" in five["body"]
    assert "Le Dantec" in by_marker["[6]"]["body"]
    auto = footnote_records_from_items(items, chapter_id="ch1")
    assert {row["number"] for row in auto} == {5, 6, 7}


def test_extract_dump_notes_parses_gutenberg_brackets():
    notes = extract_dump_notes(BERGSON_PG_NOTES)
    assert 5 in notes
    assert "volume of protoplasm" in notes[5]


def test_quotes_find_vergil_blockquote_and_emphasis():
    items, _extra = scan_quotes(
        GROTIUS, chapter_id="ch1", family="gutenberg", work_id="grotius--freedom_of_the_seas", use_llm=False
    )
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
    accepted_id = next((row["id"] for row in book.json()["items"] if row.get("decision") == "accept"), None)

    rescan = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/scan",
        json={"scope": "chapter", "chapter_id": ch_id},
    )
    assert rescan.status_code == 200
    assert rescan.json()["scope"] == "book"
    if accepted_id:
        kept = next(row for row in rescan.json()["items"] if row["id"] == accepted_id)
        assert kept.get("decision") == "accept"

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
    # FOOTNOTES is in this chapter slice, not a book-tail dump from another section.
    assert "footnotes_dump_global" not in linked["reasons"]
    assert linked["suspect"] is False

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


def test_pending_counts_undecided_suspects_only():
    summary = summarize_items(
        [
            {"suspect": False},
            {"suspect": True},
            {"suspect": True, "decision": "accept"},
            {"suspect": False, "decision": "accept"},
        ]
    )
    assert summary["pending"] == 1
    assert summary["suspect"] == 2
    assert summary["accepted"] == 2
    assert summary["total"] == 4


def test_wrap_scan_indexes_match_unwrapped_archive_scan():
    from knowledgehub.edition.lines import iter_lines
    from knowledgehub.edition.ref import normalize_edition_source

    raw = (CORPUS / "en" / "archive_scan_ocr.txt").read_text(encoding="utf-8")
    body, _apparatus, unwrapped = normalize_edition_source(raw, family="archive_scan", language="en")
    assert unwrapped is True
    raw_n = len(iter_lines(raw))
    body_n = len(iter_lines(body))
    assert body_n < raw_n
    items, _extra = scan_wrap(raw, chapter_id="c1", family="archive_scan", language="en")
    for row in items:
        assert 0 <= row["line_index"] < body_n
        assert 0 <= row["next_index"] < body_n


def test_apply_wrap_overrides_joins_megarians():
    from knowledgehub.edition.ref import build_read_edition

    items, _extra = scan_wrap(GROTIUS, chapter_id="ch1", family="gutenberg")
    hit = next(row for row in items if "Megarians" in row["prev"] and "Athenians" in row["next"])
    hit["decision"] = "accept"
    overrides = wrap_overrides_from_items(items, chapter_id="ch1")
    assert hit["line_index"] in overrides
    edition, _report = build_read_edition(
        GROTIUS,
        family="gutenberg",
        language="en",
        use_llm=False,
        wrap_overrides=overrides,
    )
    glued = " ".join(edition["reading_markdown"].split())
    assert "Megarians against the Athenians" in glued


def test_quote_scan_block_index_matches_parse_and_reject():
    from knowledgehub.edition.ref import build_read_edition

    work_id = "grotius--freedom_of_the_seas"
    items, _extra = scan_quotes(GROTIUS, chapter_id="ch1", family="gutenberg", work_id=work_id, use_llm=False)
    edition, _report = build_read_edition(
        GROTIUS,
        family="gutenberg",
        language="en",
        use_llm=False,
        work_id=work_id,
    )
    blocks = edition["blocks"]
    bq = next(row for row in items if row["mark"] == "blockquote")
    assert bq["actionable"] is True
    assert blocks[bq["block_index"]]["type"] == "blockquote"
    snippet = bq["text"].rstrip("…")[:24]
    assert snippet in (blocks[bq["block_index"]].get("text") or "")
    bq["decision"] = "reject"
    apply_quote_decisions(blocks, items, chapter_id="ch1")
    assert blocks[bq["block_index"]]["type"] == "paragraph"


def test_unclosed_quote_is_not_actionable():
    items, _extra = scan_quotes('He said "hello and never finished.\n', chapter_id="c1", family="gutenberg", use_llm=False)
    unclosed = [row for row in items if row["mark"] == "unclosed"]
    assert unclosed
    assert all(row["actionable"] is False for row in unclosed)


def _confirm_layout(client, work_id: str) -> None:
    toc = client.post(f"/api/works/{work_id}/read-edition/toc", json={"status": "none"})
    assert toc.status_code == 200, toc.text
    review = client.get(f"/api/works/{work_id}/read-edition/review")
    assert review.status_code == 200
    for sid in review.json()["health"]["untreated_flags"]:
        confirmed = client.post(
            f"/api/works/{work_id}/read-edition/structure/edit",
            json={"action": "confirm", "section_id": sid},
        )
        assert confirmed.status_code == 200
    layout = client.post(f"/api/works/{work_id}/read-edition/layout")
    assert layout.status_code == 200, layout.text
    assert layout.json()["health"]["layout_ok"] is True


def test_decide_reparses_and_refreshes_hash(tmp_path, monkeypatch):
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
    ch_id = client.get(f"/api/works/{wid}/read-edition/manifest").json()["manifest"]["chapters"][0]["chapter_id"]
    _confirm_layout(client, wid)

    parsed = client.post(f"/api/works/{wid}/read-edition/chapters/{ch_id}/parse", json={"use_llm": False})
    assert parsed.status_code == 200, parsed.text
    before_hash = parsed.json()["edition_hash"]
    before_md = parsed.json()["reading_markdown"]

    quotes = client.post(
        f"/api/works/{wid}/read-edition/hitl/quotes/scan",
        json={"scope": "chapter", "chapter_id": ch_id},
    )
    assert quotes.status_code == 200, quotes.text
    bq = next(row for row in quotes.json()["items"] if row["mark"] == "blockquote")
    decided = client.post(
        f"/api/works/{wid}/read-edition/hitl/quotes/decide",
        json={"decision": "reject", "item_ids": [bq["id"]]},
    )
    assert decided.status_code == 200, decided.text
    assert ch_id in (decided.json().get("reparsed") or [])

    from knowledgehub.edition.serialize import edition_hash as hash_blocks

    chapter = client.get(f"/api/works/{wid}/read-edition/chapters/{ch_id}")
    assert chapter.status_code == 200
    body = chapter.json()
    assert body["edition_hash"] != before_hash
    assert body["edition_hash"] == hash_blocks(body["blocks"])
    assert body["reading_markdown"] != before_md
    snippet = (bq["text"] or "").rstrip("…")[:24]
    quoted = next(b for b in body["blocks"] if snippet in (b.get("text") or ""))
    assert quoted["type"] == "paragraph"


def test_apply_wrap_overrides_function_mutates_join_next():
    from knowledgehub.edition.label_rules import label_lines_rules
    from knowledgehub.edition.lines import iter_lines

    lines = iter_lines("Alpha the\nbeta line.\n")
    labels = label_lines_rules(lines, family="gutenberg", source_text="Alpha the\nbeta line.\n")
    apply_wrap_overrides(labels, {0: True})
    assert labels[0].join_next is True
    apply_wrap_overrides(labels, {0: False})
    assert labels[0].join_next is False


def test_quote_reject_matches_snippet_after_wrap_reindex():
    from knowledgehub.edition.ref import build_read_edition

    work_id = "grotius--freedom_of_the_seas"
    items, _extra = scan_quotes(GROTIUS, chapter_id="ch1", family="gutenberg", work_id=work_id, use_llm=False)
    bq = next(row for row in items if row["mark"] == "blockquote")
    wrap_items, _extra = scan_wrap(GROTIUS, chapter_id="ch1", family="gutenberg")
    for row in wrap_items:
        row["decision"] = "accept"
    overrides = wrap_overrides_from_items(wrap_items, chapter_id="ch1")
    assert overrides
    edition, _report = build_read_edition(
        GROTIUS,
        family="gutenberg",
        language="en",
        use_llm=False,
        work_id=work_id,
        wrap_overrides=overrides,
    )
    blocks = edition["blocks"]
    stale = dict(bq)
    stale["decision"] = "reject"
    stale["block_index"] = 10_000
    apply_quote_decisions(blocks, [stale], chapter_id="ch1")
    snippet = (bq["text"] or "").rstrip("…")[:24]
    matching = [block for block in blocks if snippet in (block.get("text") or "")]
    assert matching
    assert all(block["type"] == "paragraph" for block in matching)


def test_quote_ids_do_not_embed_block_index():
    items, _extra = scan_quotes(
        GROTIUS, chapter_id="ch1", family="gutenberg", work_id="grotius--freedom_of_the_seas", use_llm=False
    )
    bq = next(row for row in items if row["mark"] == "blockquote")
    assert ":blockquote:" in bq["id"]
    assert not bq["id"].endswith(f":{bq['block_index']}")
    wrap_items, _ = scan_wrap(GROTIUS, chapter_id="ch1", family="gutenberg")
    for row in wrap_items:
        row["decision"] = "accept"
    overrides = wrap_overrides_from_items(wrap_items, chapter_id="ch1")
    rescanned, _ = scan_quotes(
        GROTIUS,
        chapter_id="ch1",
        family="gutenberg",
        work_id="grotius--freedom_of_the_seas",
        wrap_overrides=overrides or None,
        use_llm=False,
    )
    ids = {row["id"] for row in rescanned if row["mark"] == "blockquote"}
    assert bq["id"] in ids


def test_decide_item_ids_ignore_wrong_chapter_filter(tmp_path, monkeypatch):
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
    other = next((row["chapter_id"] for row in chapters if row["chapter_id"] != ch_id), "sidebar-other")

    trial = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/scan",
        json={"scope": "chapter", "chapter_id": ch_id},
    )
    assert trial.status_code == 200, trial.text
    suspect = next(row for row in trial.json()["items"] if row["suspect"])
    decided = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/decide",
        json={"decision": "accept", "item_ids": [suspect["id"]], "chapter_id": other},
    )
    assert decided.status_code == 200, decided.text
    hit = next(row for row in decided.json()["items"] if row["id"] == suspect["id"])
    assert hit.get("decision") == "accept"

    confirm = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/confirm",
        json={"chapter_id": other},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["trial_chapter_id"] == ch_id

    if len(chapters) >= 2:
        second = chapters[1]["chapter_id"]
        retry = client.post(
            f"/api/works/{wid}/read-edition/hitl/wrap/scan",
            json={"scope": "chapter", "chapter_id": second},
        )
        assert retry.status_code == 200, retry.text
        leftover = [row for row in retry.json()["items"] if row.get("chapter_id") == ch_id]
        assert leftover
        assert retry.json()["trial_chapter_id"] == ch_id
        assert retry.json()["trial_confirmed"] is True
        scanned = retry.json().get("scanned_chapter_ids") or []
        assert ch_id in scanned
        assert second in scanned


def _two_chapter_corpus(tmp: Path) -> Path:
    import json

    corpus = tmp / "corpus"
    src = corpus / "sources" / "grotius"
    src.mkdir(parents=True)
    (src / "raw").mkdir()
    (src / "raw" / "freedom_of_the_seas.txt").write_text(
        "CHAPTER I\n\n"
        "The Megarians against the\n"
        "Athenians were at war over the sea.\n\n"
        "CHAPTER II\n\n"
        "Nature itself has given the\n"
        "ocean to all people in common.\n",
        encoding="utf-8",
    )
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


def test_hitl_keeps_chapter_scans_when_switching_sections(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from knowledgehub.catalog import build_catalog
    from knowledgehub.hash import refresh_hashes
    from knowledgehub.server import create_app

    corpus = _two_chapter_corpus(tmp_path)
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
    assert len(chapters) >= 2, chapters
    first = chapters[0]["chapter_id"]
    second = chapters[1]["chapter_id"]

    trial = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/scan",
        json={"scope": "chapter", "chapter_id": first},
    )
    assert trial.status_code == 200, trial.text
    first_ids = {row["id"] for row in trial.json()["items"] if row.get("chapter_id") == first}
    assert first in (trial.json().get("scanned_chapter_ids") or [])

    confirm = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/confirm",
        json={"chapter_id": first},
    )
    assert confirm.status_code == 200, confirm.text

    other = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/scan",
        json={"scope": "chapter", "chapter_id": second},
    )
    assert other.status_code == 200, other.text
    payload = other.json()
    assert payload["trial_confirmed"] is True
    assert payload["trial_chapter_id"] == first
    scanned = payload.get("scanned_chapter_ids") or []
    assert first in scanned
    assert second in scanned
    kept = {row["id"] for row in payload["items"] if row.get("chapter_id") == first}
    assert kept == first_ids

    notes = client.post(
        f"/api/works/{wid}/read-edition/hitl/footnotes/scan",
        json={"scope": "chapter", "chapter_id": first},
    )
    assert notes.status_code == 200, notes.text
    quotes = client.post(
        f"/api/works/{wid}/read-edition/hitl/quotes/scan",
        json={"scope": "chapter", "chapter_id": first},
    )
    assert quotes.status_code == 200, quotes.text

    wrap = client.get(f"/api/works/{wid}/read-edition/hitl/wrap")
    assert wrap.status_code == 200, wrap.text
    assert first in (wrap.json().get("scanned_chapter_ids") or [])
    assert second in (wrap.json().get("scanned_chapter_ids") or [])
    assert {row["id"] for row in wrap.json()["items"] if row.get("chapter_id") == first} == first_ids

    overview = client.get(f"/api/works/{wid}/read-edition/hitl")
    assert overview.status_code == 200
    kinds = overview.json()["kinds"]
    assert first in (kinds["wrap"]["scanned_chapter_ids"] or [])
    assert kinds["footnotes"]["status"] == "trial"
    assert kinds["quotes"]["status"] == "trial"


def test_hitl_unconfirmed_trial_follows_latest_chapter_scan(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from knowledgehub.catalog import build_catalog
    from knowledgehub.hash import refresh_hashes
    from knowledgehub.server import create_app

    corpus = _two_chapter_corpus(tmp_path)
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
    assert len(chapters) >= 2, chapters
    first = chapters[0]["chapter_id"]
    second = chapters[1]["chapter_id"]

    first_scan = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/scan",
        json={"scope": "chapter", "chapter_id": first},
    )
    assert first_scan.status_code == 200, first_scan.text
    assert first_scan.json()["trial_chapter_id"] == first
    assert first_scan.json()["trial_confirmed"] is False
    first_ids = {row["id"] for row in first_scan.json()["items"] if row.get("chapter_id") == first}
    first_accepted = next((row["id"] for row in first_scan.json()["items"] if row["suspect"]), None)
    if first_accepted:
        decided = client.post(
            f"/api/works/{wid}/read-edition/hitl/wrap/decide",
            json={"decision": "accept", "item_ids": [first_accepted]},
        )
        assert decided.status_code == 200

    second_scan = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/scan",
        json={"scope": "chapter", "chapter_id": second},
    )
    assert second_scan.status_code == 200, second_scan.text
    payload = second_scan.json()
    assert payload["trial_confirmed"] is False
    assert payload["trial_chapter_id"] == second
    scanned = payload.get("scanned_chapter_ids") or []
    assert first in scanned
    assert second in scanned
    kept = {row["id"] for row in payload["items"] if row.get("chapter_id") == first}
    assert kept == first_ids
    if first_accepted:
        kept_row = next(row for row in payload["items"] if row["id"] == first_accepted)
        assert kept_row.get("decision") == "accept"

    confirm = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/confirm",
        json={"chapter_id": second},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["trial_chapter_id"] == second
    assert confirm.json()["trial_confirmed"] is True

    after = client.post(
        f"/api/works/{wid}/read-edition/hitl/wrap/scan",
        json={"scope": "chapter", "chapter_id": first},
    )
    assert after.status_code == 200, after.text
    assert after.json()["trial_chapter_id"] == second
    assert after.json()["trial_confirmed"] is True
    assert {row["id"] for row in after.json()["items"] if row.get("chapter_id") == first} == first_ids
