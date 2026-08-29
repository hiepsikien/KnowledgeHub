from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledgehub.edition.ref_parser import parse_manuscript_to_ref

CORPUS = Path(__file__).resolve().parent / "fixtures" / "ref_corpus"


def test_hamlet_dialogue_blocks():
    raw = (CORPUS / "en" / "shakespeare_hamlet.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    dialogues = [b for b in edition["blocks"] if b["type"] == "dialogue"]
    assert len(dialogues) >= 20
    assert edition["content_kind"] == "drama"
    assert any(b.get("speaker") == "BARNARDO" for b in dialogues)
    assert any("there" in b.get("text", "").lower() for b in dialogues)


def test_aquinas_list_items():
    raw = (CORPUS / "en" / "aquinas_summa.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="scholastic", strip_first=True)
    items = [b for b in edition["blocks"] if b["type"] == "list_item"]
    assert len(items) >= 8
    assert edition["content_kind"] == "scholastic"
    assert items[0]["text"].startswith("(1)")


def test_whitman_stanzas():
    raw = (CORPUS / "en" / "whitman_grass.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    stanzas = [b for b in edition["blocks"] if b["type"] == "stanza"]
    assert len(stanzas) >= 10
    assert "\n" in stanzas[0]["text"]


def test_qua_deo_ngang_stanzas():
    raw = (CORPUS / "vi" / "qua_deo_ngang.txt").read_text(encoding="utf-8")
    edition, report = parse_manuscript_to_ref(raw, language="vi", family="plain", strip_first=False)
    stanzas = [b for b in edition["blocks"] if b["type"] == "stanza"]
    assert len(stanzas) >= 6
    assert report.get("apparatus_dropped")
    assert edition["content_kind"] == "mixed"


def test_wiki_apparatus_dropped():
    raw = (CORPUS / "vi" / "nam_cao_chi_pheo.txt").read_text(encoding="utf-8")
    edition, report = parse_manuscript_to_ref(raw, language="vi", family="plain", strip_first=False)
    assert "5415" not in edition["reading_markdown"]
    assert any("5415" in line for line in report.get("apparatus_dropped", []))


def test_archive_scan_unwrap():
    raw = (CORPUS / "en" / "archive_scan_ocr.txt").read_text(encoding="utf-8")
    edition, report = parse_manuscript_to_ref(raw, language="en", family="archive_scan", strip_first=False)
    md = edition["reading_markdown"]
    assert "typical of scanned" in md.replace("\n", " ")
    assert report.get("unwrapped") is True


def test_heading_em_span():
    from knowledgehub.edition.inline_spans import annotate_inline_spans

    text = "_By the Law of Nations navigation is free to all persons whatsoever_"
    spans = annotate_inline_spans(text)
    assert any(s.style == "em" for s in spans)


def test_balanced_paren_span():
    from knowledgehub.edition.inline_spans import annotate_inline_spans

    text = "Từ năm (1570-1597) trở về sau, lời thanh-nghị suy đồi."
    spans = annotate_inline_spans(text)
    paren = [s for s in spans if s.text.startswith("(")]
    assert len(paren) == 1
    assert paren[0].text == "(1570-1597)"


@pytest.mark.parametrize("min_overall", [9])
def test_qa_report_thresholds(min_overall: int):
    report_path = CORPUS / "qa_report.json"
    if not report_path.exists():
        pytest.skip("qa_report.json not present")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for row in report.get("results", []):
        scores = row.get("scores") or {}
        overall = scores.get("overall")
        if overall is not None:
            assert overall >= min_overall, row.get("id")
    assert report.get("verdict_fail", 1) == 0
