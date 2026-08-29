from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from knowledgehub.edition.fidelity import run_fidelity_checks
from knowledgehub.edition.ref_parser import parse_manuscript_to_ref
from knowledgehub.edition.ref_qa import parse_and_qa, qa_read_edition

CORPUS_DIR = Path(__file__).resolve().parent / "fixtures" / "ref_corpus"
GROTIUS = CORPUS_DIR / "en" / "grotius_treatise.txt"

MOCK_LLM = json.dumps(
    {
        "scores": {
            "text_preservation": 9,
            "block_structure": 8,
            "join_quality": 9,
            "inline_spans": 8,
            "overall": 8,
        },
        "summary_vi": "Parse giữ nguyên văn bản; join và footnote hợp lý.",
        "issues": [],
        "verdict": "pass",
    },
    ensure_ascii=False,
)


def test_fidelity_subsequence_passes_grotius():
    raw = GROTIUS.read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    result = run_fidelity_checks(raw, edition)
    assert result["passed"] is True
    assert result["critical_count"] == 0


def test_fidelity_fails_on_rewritten_word():
    raw = GROTIUS.read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    edition["blocks"][1]["text"] = edition["blocks"][1]["text"].replace("Law", "Statute")
    result = run_fidelity_checks(raw, edition)
    assert result["passed"] is False
    sub = next(c for c in result["checks"] if c["id"] == "text_subsequence")
    assert sub["passed"] is False


def test_qa_read_edition_rules_only():
    raw = GROTIUS.read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    report = qa_read_edition(raw, edition, use_llm=False)
    assert report["passed"] is True
    assert report["fidelity"]["passed"] is True
    assert report["llm"] is None


@patch("knowledgehub.edition.ref_qa.complete_chat", return_value=MOCK_LLM)
def test_qa_read_edition_with_mock_llm(mock_chat):
    raw = GROTIUS.read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language="en", family="gutenberg", strip_first=False)
    report = qa_read_edition(raw, edition, use_llm=True, model="deepseek-v4-pro")
    assert report["passed"] is True
    assert report["llm"]["scores"]["overall"] == 8
    assert mock_chat.called


@patch("knowledgehub.edition.ref_qa.complete_chat", return_value=MOCK_LLM)
def test_parse_and_qa(mock_chat):
    raw = GROTIUS.read_text(encoding="utf-8")
    edition, parse_report, qa_report = parse_and_qa(
        raw,
        language="en",
        family="gutenberg",
        strip_first=False,
        use_llm_qa=True,
        qa_model="deepseek-v4-pro",
    )
    assert edition["edition_format"] == "ref/1"
    assert parse_report["validation_errors"] == []
    assert qa_report["passed"] is True
    assert qa_report["llm"]["verdict"] == "pass"


@pytest.mark.parametrize(
    "sample_id,file_path,language,family,strip",
    [
        ("grotius_treatise", "en/grotius_treatise.txt", "en", "gutenberg", False),
        ("nam_cao_chi_pheo", "vi/nam_cao_chi_pheo.txt", "vi", "plain", False),
    ],
)
def test_corpus_fidelity_rules(sample_id: str, file_path: str, language: str, family: str, strip: bool):
    raw = (CORPUS_DIR / file_path).read_text(encoding="utf-8")
    edition, _ = parse_manuscript_to_ref(raw, language=language, family=family, strip_first=strip)
    result = run_fidelity_checks(raw, edition)
    assert result["passed"], f"{sample_id}: {result}"


@pytest.mark.llm
def test_llm_qa_grotius_live():
    """Live LLM QA — skipped unless pytest -m llm and API keys set."""
    raw = GROTIUS.read_text(encoding="utf-8")
    _, _, qa_report = parse_and_qa(
        raw,
        language="en",
        family="gutenberg",
        strip_first=False,
        use_llm_qa=True,
    )
    assert qa_report["fidelity"]["passed"]
    assert qa_report["llm"] is not None
    assert "error" not in qa_report["llm"]
    assert qa_report["llm"]["scores"]["overall"] >= 6
