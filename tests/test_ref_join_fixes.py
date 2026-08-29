from __future__ import annotations

from pathlib import Path

from knowledgehub.edition.ref_parser import parse_manuscript_to_ref

CORPUS = Path(__file__).resolve().parent / "fixtures" / "ref_corpus"


def test_grotius_poetry_blockquote_merged():
    raw = (CORPUS / "en" / "grotius_treatise.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    md = edition["reading_markdown"]
    assert "What men, what monsters" in md
    assert "cruel seas again._”[6]" in md
    assert any(b.get("type") == "blockquote" for b in edition["blocks"])


def test_vi_paragraphs_not_over_merged():
    raw = (CORPUS / "vi" / "grotius_vi_chviii.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="vi", family="plain", strip_first=False)
    assert len(edition["blocks"]) >= 6
    texts = [b.get("text") or "" for b in edition["blocks"] if b.get("type") == "paragraph"]
    assert any(t.startswith("Nếu người Bồ Đào Nha") for t in texts)
    assert any(t.startswith("Tự nhiên vốn đã") for t in texts)
    assert any(t.startswith("Nhưng khi động sản") for t in texts)


def test_blank_line_splits_subtitle():
    raw = (CORPUS / "vi" / "grotius_vi_chviii.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="vi", family="plain", strip_first=False)
    paragraphs = [b for b in edition["blocks"] if b.get("type") == "paragraph"]
    assert paragraphs[0]["text"].startswith("Theo Luật các dân tộc")
    assert paragraphs[1]["text"].startswith("Nếu người Bồ Đào Nha")
    assert "Theo Luật" not in paragraphs[1]["text"]


def test_pg_mid_sentence_joins():
    raw = (CORPUS / "en" / "grotius_treatise.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    md = edition["reading_markdown"]
    assert "Megarians against the Athenians" in md.replace("\n", " ")


def test_publisher_imprint_merged():
    raw = (CORPUS / "en" / "locke_second_treatise.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    imprint = " ".join(str(b.get("text") or "") for b in edition["blocks"])
    assert "LONDON PRINTED MDCLXXXVIII" in imprint
    assert "REPRINTED" in imprint


def test_wiki_junk_stripped():
    raw = (CORPUS / "vi" / "qua_deo_ngang.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="vi", family="plain", strip_first=False)
    md = edition["reading_markdown"]
    assert "3692" not in md
    assert "Bước xuống Đèo Ngang" in md


def test_year_paren_not_footnote():
    raw = (CORPUS / "vi" / "le_kien_van_cao_si.txt").read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="vi", family="plain", strip_first=False)
    for block in edition["blocks"]:
        for span in block.get("spans") or []:
            if span.get("text") == "(1505)":
                assert span["style"] == "paren_aside"
