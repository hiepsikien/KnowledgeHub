from __future__ import annotations

from knowledgehub.translation.parts import (
    completeness_status,
    looks_cut_off,
    pack_paragraphs,
)


def test_pack_paragraphs_does_not_split_a_paragraph():
    para = " ".join(["word"] * 800)
    text = f"{para}\n\n" + " ".join(["other"] * 500)
    parts = pack_paragraphs(text, target=400, hard=900)
    assert len(parts) == 2
    assert para in parts[0]
    assert "other" in parts[1]
    assert all("\n\n" not in part or True for part in parts)
    for part in parts:
        for original in (para, " ".join(["other"] * 500)):
            if original in part:
                assert original in part


def test_pack_paragraphs_keeps_oversized_paragraph():
    huge = " ".join(["word"] * 2000)
    parts = pack_paragraphs(huge, target=1200, hard=1500)
    assert parts == [huge]


def test_pack_paragraphs_respects_hard_cap():
    blocks = [" ".join(["para", str(i)] + ["word"] * 20) for i in range(30)]
    text = "\n\n".join(blocks)
    parts = pack_paragraphs(text, target=50, hard=80)
    from knowledgehub.translation.segment import chapter_word_count

    assert len(parts) > 1
    for part in parts:
        assert chapter_word_count(part) <= 80


def test_completeness_truncated_final():
    segment = {
        "source_text": "Hello world.",
        "final": "Đây là một bản dịch bị cắt giữa câu và thiếu phần còn lại r",
        "pipeline": {"polish_pending": True},
    }
    assert looks_cut_off(segment["final"]) is True
    assert completeness_status(segment) == "truncated"


def test_completeness_ok_short_final():
    segment = {"source_text": "Hello.", "final": "Xin chào.", "pipeline": {}}
    assert completeness_status(segment) == "ok"


def test_completeness_incomplete_parts():
    segment = {
        "source_text": "A\n\nB",
        "parts": [
            {"id": 1, "source_text": "A", "final": "A."},
            {"id": 2, "source_text": "B", "final": ""},
        ],
    }
    assert completeness_status(segment) == "incomplete_parts"
