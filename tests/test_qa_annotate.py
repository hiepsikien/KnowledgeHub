from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from knowledgehub.translation.annotate import annotate_segment
from knowledgehub.translation.llm_json import parse_json_object
from knowledgehub.translation.project import init_translation_project, select_translation_mode
from knowledgehub.translation.providers import ProviderError
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


def test_parse_json_object_extracts_wrapped_object():
    assert parse_json_object('Here you go:\n{"scores": {"overall": 8}}\nThanks.') == {
        "scores": {"overall": 8}
    }


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
    with patch("knowledgehub.translation.qa.complete_chat", return_value=qa_json) as mock_chat:
        result = qa_segment("grotius--freedom_of_the_seas", "I")
    user = mock_chat.call_args[0][0][1]["content"]
    assert "--- VIETNAMESE ANNOTATIONS ---" not in user
    assert result["scores"]["overall"] == 9
    chi = json.loads((corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json").read_text())
    assert chi["qa"]["mode"] == "tight"
    assert chi["qa"]["scores"]["fidelity"] == 9
    assert chi["qa"]["annotations_reviewed"] == 0


def test_qa_segment_reviews_existing_annotations(corpus: Path):
    _lock_tight(corpus)
    ann_path = corpus / "translations/grotius--freedom_of_the_seas/annotations.json"
    ann_path.write_text(
        json.dumps(
            {
                "annotations": [
                    {
                        "id": "grotius--freedom_of_the_seas--chi--fn-1",
                        "chapter": "I",
                        "kind": "footnote",
                        "marker": "[1]",
                        "title_vi": "Chú thích [1]",
                        "body_vi": "Pliny sai tên.",
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    qa_json = json.dumps(
        {
            "scores": {
                "fidelity": 8,
                "fluency": 8,
                "terminology": 8,
                "completeness": 10,
                "overall": 8,
                "annotations": 6,
            },
            "summary_vi": "Bản dịch ổn; chú thích [1] nhầm.",
            "issues": [
                {
                    "severity": "minor",
                    "category": "annotation",
                    "note_vi": "Sai tên Pliny.",
                    "translation_excerpt": "Pliny sai tên.",
                    "annotation_id": "grotius--freedom_of_the_seas--chi--fn-1",
                }
            ],
        }
    )
    with patch("knowledgehub.translation.qa.complete_chat", return_value=qa_json) as mock_chat:
        result = qa_segment("grotius--freedom_of_the_seas", "I")
    prompt = mock_chat.call_args[0][0]
    user = prompt[1]["content"]
    assert "--- VIETNAMESE ANNOTATIONS ---" in user
    assert "Pliny sai tên." in user
    assert result["annotations_reviewed"] == 1
    assert result["annotation_issue_count"] == 1
    assert result["scores"]["annotations"] == 6
    chi = json.loads((corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json").read_text())
    assert chi["qa"]["issues"][0]["target"] == "annotation"


def test_approve_qa_issues_one_and_all(corpus: Path):
    _lock_tight(corpus)
    chi = corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["qa"] = {
        "scores": {"fidelity": 8, "fluency": 8, "terminology": 8, "completeness": 10, "overall": 8},
        "issues": [
            {"severity": "minor", "category": "terminology", "note_vi": "A"},
            {"severity": "minor", "category": "fidelity", "note_vi": "B"},
        ],
    }
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from knowledgehub.translation.qa import approve_qa_issues

    one = approve_qa_issues("grotius--freedom_of_the_seas", "I", index=0)
    assert one["open_issue_count"] == 1
    assert one["applied_count"] == 0
    assert one["issues"][0]["approved"] is True
    assert one["issues"][1].get("approved") is not True
    stored = json.loads(chi.read_text(encoding="utf-8"))
    assert stored["final"] == "Bản dịch tight."
    all_ok = approve_qa_issues("grotius--freedom_of_the_seas", "I")
    assert all_ok["open_issue_count"] == 0
    assert all(issue["approved"] for issue in all_ok["issues"])


def test_approve_qa_rewrites_final_from_excerpt(corpus: Path):
    _lock_tight(corpus)
    chi = corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["final"] = "Người Đông Ấn cũng không phải là những kẻ ngu muội hay kém cỏi."
    payload["drafts"]["tight"] = payload["final"]
    payload["qa"] = {
        "scores": {"fidelity": 8, "fluency": 8, "terminology": 8, "completeness": 10, "overall": 8},
        "issues": [
            {
                "severity": "minor",
                "category": "fidelity",
                "note_vi": "unthinking ≠ kém cỏi",
                "translation_excerpt": "ngu muội hay kém cỏi",
            }
        ],
    }
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from knowledgehub.translation.qa import approve_qa_issues

    result = approve_qa_issues(
        "grotius--freedom_of_the_seas",
        "I",
        index=0,
        replacement="ngu muội hay thiếu suy nghĩ",
    )
    assert result["applied_count"] == 1
    assert result["issues"][0]["applied_replacement"] == "ngu muội hay thiếu suy nghĩ"
    stored = json.loads(chi.read_text(encoding="utf-8"))
    assert stored["final"] == "Người Đông Ấn cũng không phải là những kẻ ngu muội hay thiếu suy nghĩ."
    assert stored["drafts"]["tight"] == stored["final"]


def test_approve_qa_all_applies_replacements(corpus: Path):
    _lock_tight(corpus)
    chi = corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["final"] = "AAA rồi BBB."
    payload["drafts"]["tight"] = payload["final"]
    payload["qa"] = {
        "scores": {"fidelity": 8, "fluency": 8, "terminology": 8, "completeness": 10, "overall": 8},
        "issues": [
            {"severity": "minor", "category": "fidelity", "note_vi": "A", "translation_excerpt": "AAA"},
            {"severity": "minor", "category": "fidelity", "note_vi": "B", "translation_excerpt": "BBB"},
        ],
    }
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from knowledgehub.translation.qa import approve_qa_issues

    result = approve_qa_issues(
        "grotius--freedom_of_the_seas",
        "I",
        replacements={0: "XXX", 1: "YYY"},
    )
    assert result["applied_count"] == 2
    assert result["open_issue_count"] == 0
    stored = json.loads(chi.read_text(encoding="utf-8"))
    assert stored["final"] == "XXX rồi YYY."


def test_approve_qa_missing_excerpt_does_not_rewrite(corpus: Path):
    _lock_tight(corpus)
    chi = corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["qa"] = {
        "scores": {"fidelity": 8, "fluency": 8, "terminology": 8, "completeness": 10, "overall": 8},
        "issues": [
            {
                "severity": "minor",
                "category": "fidelity",
                "note_vi": "A",
                "translation_excerpt": "không có trong bản dịch",
            }
        ],
    }
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from knowledgehub.translation.qa import approve_qa_issues

    with pytest.raises(ValueError, match="Không thấy đoạn VI"):
        approve_qa_issues(
            "grotius--freedom_of_the_seas",
            "I",
            index=0,
            replacement="câu mới",
        )
    stored = json.loads(chi.read_text(encoding="utf-8"))
    assert stored["final"] == "Bản dịch tight."
    assert stored["qa"]["issues"][0].get("approved") is not True


def test_replace_excerpt_tolerates_quote_mismatch():
    from knowledgehub.translation.qa import _replace_excerpt

    text = (
        "áp bức, tước đoạt, khuất phục họ, và “khiến họ trở thành con cái "
        "địa ngục gấp hai lần chính mình,”* theo cách của những người Pharisêu"
    )
    excerpt = "khuất phục họ, và 'khiến họ trở thành con cái địa ngục gấp hai lần chính mình'"
    replacement = (
        "khuất phục và cải đạo họ, và “khiến họ trở thành con cái "
        "địa ngục gấp hai lần chính mình,”"
    )
    updated, count = _replace_excerpt(text, excerpt, replacement)
    assert count == 1
    assert "khuất phục và cải đạo họ" in updated
    assert updated.endswith("* theo cách của những người Pharisêu")
    assert 'mình,”,”' not in updated


def test_approve_qa_rewrites_curly_quoted_excerpt(corpus: Path):
    _lock_tight(corpus)
    chi = corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["final"] = (
        "chứ không phải những kẻ đến để áp bức, tước đoạt, khuất phục họ, "
        "và “khiến họ trở thành con cái địa ngục gấp hai lần chính mình,”* "
        "theo cách của những người Pharisêu’."
    )
    payload["drafts"]["tight"] = payload["final"]
    payload["qa"] = {
        "scores": {"fidelity": 8, "fluency": 8, "terminology": 8, "completeness": 10, "overall": 8},
        "issues": [
            {
                "severity": "minor",
                "category": "completeness",
                "note_vi": "Thiếu proselytize.",
                "translation_excerpt": (
                    "khuất phục họ, và 'khiến họ trở thành con cái địa ngục gấp hai lần chính mình'"
                ),
            }
        ],
    }
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from knowledgehub.translation.qa import approve_qa_issues

    result = approve_qa_issues(
        "grotius--freedom_of_the_seas",
        "I",
        index=0,
        replacement="khuất phục và cải đạo họ, và “khiến họ trở thành con cái địa ngục gấp hai lần chính mình,”",
    )
    assert result["applied_count"] == 1
    stored = json.loads(chi.read_text(encoding="utf-8"))
    assert "khuất phục và cải đạo họ" in stored["final"]
    assert stored["final"].count("*") == 1


def test_approve_qa_rewrites_annotation_body(corpus: Path):
    _lock_tight(corpus)
    ann_path = corpus / "translations/grotius--freedom_of_the_seas/annotations.json"
    ann_id = "grotius--freedom_of_the_seas--chi--fn-1"
    ann_path.write_text(
        json.dumps(
            {
                "annotations": [
                    {
                        "id": ann_id,
                        "chapter": "I",
                        "kind": "footnote",
                        "marker": "[1]",
                        "title_vi": "Chú thích [1]",
                        "body_vi": "Pliny sai tên.",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    chi = corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["qa"] = {
        "scores": {"fidelity": 8, "fluency": 8, "terminology": 8, "completeness": 10, "overall": 8},
        "issues": [
            {
                "severity": "minor",
                "category": "annotation",
                "note_vi": "Sai tên.",
                "translation_excerpt": "Pliny sai tên.",
                "annotation_id": ann_id,
                "target": "annotation",
            }
        ],
    }
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from knowledgehub.translation.qa import approve_qa_issues, reopen_qa_issues

    result = approve_qa_issues(
        "grotius--freedom_of_the_seas",
        "I",
        index=0,
        replacement="Pliny the Elder, nhà sử gia La Mã.",
    )
    assert result["applied_count"] == 1
    stored_ann = json.loads(ann_path.read_text(encoding="utf-8"))
    assert stored_ann["annotations"][0]["body_vi"] == "Pliny the Elder, nhà sử gia La Mã."
    stored_seg = json.loads(chi.read_text(encoding="utf-8"))
    assert stored_seg["final"] == "Bản dịch tight."

    reopened = reopen_qa_issues("grotius--freedom_of_the_seas", "I", index=0)
    assert reopened["reverted_count"] == 1
    restored = json.loads(ann_path.read_text(encoding="utf-8"))
    assert restored["annotations"][0]["body_vi"] == "Pliny sai tên."


def test_reopen_qa_issues_unstamps_without_rewrite(corpus: Path):
    _lock_tight(corpus)
    chi = corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["qa"] = {
        "scores": {"fidelity": 8, "fluency": 8, "terminology": 8, "completeness": 10, "overall": 8},
        "issues": [
            {"severity": "minor", "category": "terminology", "note_vi": "A", "approved": True},
            {"severity": "minor", "category": "fidelity", "note_vi": "B", "approved": True},
        ],
        "open_issue_count": 0,
        "approved_at": "2026-08-28T05:21:30+00:00",
    }
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from knowledgehub.translation.qa import reopen_qa_issues

    one = reopen_qa_issues("grotius--freedom_of_the_seas", "I", index=0)
    assert one["open_issue_count"] == 1
    assert one["issues"][0].get("approved") is not True
    assert one["issues"][1]["approved"] is True
    all_ok = reopen_qa_issues("grotius--freedom_of_the_seas", "I")
    assert all_ok["open_issue_count"] == 2
    stored = json.loads(chi.read_text(encoding="utf-8"))
    assert stored["final"] == "Bản dịch tight."
    assert "approved_at" not in stored["qa"]
    assert all(not issue.get("approved") for issue in stored["qa"]["issues"])


def test_reopen_qa_reverts_applied_replacement(corpus: Path):
    _lock_tight(corpus)
    chi = corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    payload = json.loads(chi.read_text(encoding="utf-8"))
    payload["final"] = "ngu muội hay thiếu suy nghĩ"
    payload["drafts"]["tight"] = payload["final"]
    payload["qa"] = {
        "scores": {"fidelity": 8, "fluency": 8, "terminology": 8, "completeness": 10, "overall": 8},
        "issues": [
            {
                "severity": "minor",
                "category": "fidelity",
                "note_vi": "A",
                "translation_excerpt": "ngu muội hay kém cỏi",
                "applied_replacement": "ngu muội hay thiếu suy nghĩ",
                "approved": True,
            }
        ],
        "open_issue_count": 0,
    }
    chi.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from knowledgehub.translation.qa import reopen_qa_issues

    result = reopen_qa_issues("grotius--freedom_of_the_seas", "I", index=0)
    assert result["reverted_count"] == 1
    stored = json.loads(chi.read_text(encoding="utf-8"))
    assert stored["final"] == "ngu muội hay kém cỏi"
    assert stored["drafts"]["tight"] == stored["final"]
    assert stored["qa"]["issues"][0].get("approved") is not True
    assert "applied_replacement" not in stored["qa"]["issues"][0]


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
    with patch("knowledgehub.translation.annotate.complete_prompt", return_value=ann_json):
        result = annotate_segment("grotius--freedom_of_the_seas", "I")
    assert result["added_or_updated"] == 1
    store = json.loads((corpus / "translations/grotius--freedom_of_the_seas/annotations.json").read_text())
    assert len(store["annotations"]) == 1
    assert store["annotations"][0]["body_vi"].startswith("Pliny")
    assert store["annotations"][0]["title_vi"] == "Pliny [1]"


def test_annotate_skips_duplicate_glossary_term(corpus: Path):
    _lock_tight(corpus)
    ann_path = corpus / "translations/grotius--freedom_of_the_seas/annotations.json"
    ann_path.write_text(
        json.dumps(
            {
                "annotations": [
                    {
                        "id": "keep-glossary",
                        "segment_id": "grotius--freedom_of_the_seas--chii",
                        "chapter": "II",
                        "kind": "glossary",
                        "anchor_text": "Luật các dân tộc",
                        "title_vi": "Luật các dân tộc",
                        "body_vi": "Jus gentium.",
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    fresh = json.dumps(
        {
            "annotations": [
                {
                    "id": "grotius--freedom_of_the_seas--chi--glossary-law-of-nations",
                    "kind": "glossary",
                    "anchor_text": "Luật các dân tộc",
                    "title_vi": "Luật các dân tộc (Jus Gentium)",
                    "body_vi": "Bản trùng.",
                },
                {
                    "id": "grotius--freedom_of_the_seas--chi--fn-17",
                    "marker": "[17]",
                    "kind": "footnote",
                    "anchor_text": "Gordian",
                    "body_vi": "Hoàng đế Gordian.",
                },
            ]
        }
    )
    with patch("knowledgehub.translation.annotate.complete_prompt", return_value=fresh):
        result = annotate_segment("grotius--freedom_of_the_seas", "I")
    store = json.loads(ann_path.read_text(encoding="utf-8"))
    glossary = [row for row in store["annotations"] if row.get("kind") == "glossary"]
    assert len(glossary) == 1
    assert glossary[0]["id"] == "keep-glossary"
    assert result["added_or_updated"] == 1
    assert any(row.get("title_vi") == "Gordian [17]" for row in store["annotations"])


def test_annotate_skips_context_that_restates_a_footnote(corpus: Path):
    _lock_tight(corpus)
    chi = corpus / "translations/grotius--freedom_of_the_seas/segments/chi.json"
    row = json.loads(chi.read_text(encoding="utf-8"))
    row["final"] = (
        "Augustine,[12] khi người Israel bị khước từ lối đi vô hại qua lãnh thổ."
    )
    chi.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fresh = json.dumps(
        {
            "annotations": [
                {
                    "id": "fn-12",
                    "marker": "[12]",
                    "kind": "footnote",
                    "anchor_text": "Augustine",
                    "body_vi": "Ông lập luận rằng việc từ chối một lối đi vô hại là lý do chính đáng.",
                },
                {
                    "id": "ctx-passage",
                    "kind": "context",
                    "anchor_text": "lối đi vô hại",
                    "title_vi": "Bối cảnh pháp lý",
                    "body_vi": "Khái niệm transitus innoxius.",
                },
            ]
        }
    )
    with patch("knowledgehub.translation.annotate.complete_prompt", return_value=fresh):
        result = annotate_segment("grotius--freedom_of_the_seas", "I")
    store = json.loads(
        (corpus / "translations/grotius--freedom_of_the_seas/annotations.json").read_text()
    )
    kinds = [row.get("kind") for row in store["annotations"]]
    assert kinds == ["footnote"]
    assert result["added_or_updated"] == 1


def test_qa_rejects_out_of_range_score(corpus: Path):
    _lock_tight(corpus)
    qa_json = json.dumps(
        {
            "scores": {
                "fidelity": 11,
                "fluency": 8,
                "terminology": 9,
                "completeness": 10,
                "overall": 9,
            },
            "summary_vi": "Bad score.",
            "issues": [],
        }
    )
    with patch("knowledgehub.translation.qa.complete_chat", return_value=qa_json):
        with pytest.raises(ProviderError, match="out of range"):
            qa_segment("grotius--freedom_of_the_seas", "I")


def test_annotate_replaces_segment_orphans(corpus: Path):
    _lock_tight(corpus)
    ann_path = corpus / "translations/grotius--freedom_of_the_seas/annotations.json"
    ann_path.write_text(
        json.dumps(
            {
                "annotations": [
                    {
                        "id": "stale-fn",
                        "segment_id": "grotius--freedom_of_the_seas--chi",
                        "chapter": "I",
                        "marker": "[99]",
                        "kind": "footnote",
                        "body_vi": "orphan",
                    },
                    {
                        "id": "keep-chii",
                        "segment_id": "grotius--freedom_of_the_seas--chii",
                        "chapter": "II",
                        "kind": "context",
                        "body_vi": "keep",
                    },
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    fresh = json.dumps(
        {
            "annotations": [
                {
                    "id": "grotius--freedom_of_the_seas--chi--fn-1",
                    "marker": "[1]",
                    "kind": "footnote",
                    "body_vi": "Pliny.",
                }
            ]
        }
    )
    with patch("knowledgehub.translation.annotate.complete_prompt", return_value=fresh):
        annotate_segment("grotius--freedom_of_the_seas", "I")
    store = json.loads(ann_path.read_text(encoding="utf-8"))
    ids = {a["id"] for a in store["annotations"]}
    assert "stale-fn" not in ids
    assert "keep-chii" in ids
    assert "grotius--freedom_of_the_seas--chi--fn-1" in ids


def test_qa_requires_locked_mode(corpus: Path):
    init_translation_project("grotius--freedom_of_the_seas")
    with pytest.raises(ValueError, match="translation_mode not locked"):
        qa_segment("grotius--freedom_of_the_seas", "I")
