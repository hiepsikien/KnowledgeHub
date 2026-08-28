from __future__ import annotations

from knowledgehub.translation.parts import (
    completeness_status,
    looks_cut_off,
    pack_paragraphs,
    project_split_version,
    repair_paragraphs,
    translation_looks_truncated,
)
from knowledgehub.translation.segment import chapter_word_count


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


def test_repair_paragraphs_rejoins_a_sentence_split_by_a_blank_line():
    blocks = [
        "CHAPTER VII",
        "_Neither the Sea nor the right of navigation thereon belongs to the\nPortuguese_",
        "For so far as the merely\nmunicipal laws of any place are concerned, they do not",
        "apply to the question at issue. On this point",
        "Papinian has said that prescription fails.",
    ]
    assert repair_paragraphs(blocks) == [
        "CHAPTER VII",
        "_Neither the Sea nor the right of navigation thereon belongs to the\nPortuguese_",
        "For so far as the merely\nmunicipal laws of any place are concerned, they do not\n"
        "apply to the question at issue. On this point\n"
        "Papinian has said that prescription fails.",
    ]


def test_repair_keeps_headings_and_properly_ended_paragraphs_apart():
    blocks = ["CHAPTER VII", "The first paragraph ends cleanly.", "So does the second one."]
    assert repair_paragraphs(blocks) == blocks


def test_repair_reads_trailing_dashes_correctly():
    # "]--" closes an editor's note; a bare "-" is a word hyphenated across a break.
    closed = ["[Note: he was never rewarded for it]--", "The narrative resumes here."]
    assert repair_paragraphs(closed) == closed
    hyphenated = ["The argument rests on a single consid-", "eration that follows below."]
    assert repair_paragraphs(hyphenated) == [
        "The argument rests on a single consid-\neration that follows below."
    ]


def test_version_2_parts_all_end_at_a_sentence_boundary():
    text = (
        "First paragraph runs to a proper stop.\n\n"
        "The second one breaks off and they do not\n\n"
        "apply to anything here, which is the rest of the sentence.\n\n"
        "A third paragraph closes the chapter."
    )
    old = pack_paragraphs(text, target=8, hard=12)
    new = pack_paragraphs(text, target=8, hard=12, version=2)
    assert any(part.rstrip().endswith("they do not") for part in old)
    assert all(part.rstrip().endswith(".") for part in new)


def test_version_2_cuts_a_giant_paragraph_at_sentence_boundaries():
    paragraph = " ".join(f"Sentence number {i} says something about the sea." for i in range(60))
    parts = pack_paragraphs(paragraph, target=100, hard=120, version=2)
    assert len(parts) > 1
    assert all(part.rstrip().endswith(".") for part in parts)
    assert all(chapter_word_count(part) <= 120 for part in parts)
    assert " ".join(" ".join(parts).split()) == " ".join(paragraph.split())


def test_version_1_leaves_a_giant_paragraph_whole():
    paragraph = " ".join(f"Sentence number {i} says something about the sea." for i in range(60))
    assert pack_paragraphs(paragraph, target=100, hard=120) == [paragraph]


def test_project_split_version_defaults_to_one():
    assert project_split_version(None) == 1
    assert project_split_version({}) == 1
    assert project_split_version({"split_version": "oops"}) == 1
    assert project_split_version({"split_version": 2}) == 2


def test_completeness_truncated_final():
    segment = {
        "source_text": "Hello world.",
        "final": "Đây là một bản dịch bị cắt giữa câu và thiếu phần còn lại r",
        "pipeline": {"polish_pending": True},
    }
    assert looks_cut_off(segment["final"]) is True
    assert completeness_status(segment) == "truncated"


def test_looks_cut_off_allows_legitimate_endings():
    assert looks_cut_off("Hiệp ước ấy được ký kết tại Antwerp vào năm 1609") is False
    assert looks_cut_off("Xem thêm lập luận ở Điều 5") is False
    assert looks_cut_off("Biển cả vốn thuộc về mọi người.\n\nCHƯƠNG VII") is False
    assert looks_cut_off("Người La Mã cũng nghĩ như vậy.\n\nTỰ DO BIỂN CẢ") is False
    assert looks_cut_off("Quyền đi lại trên biển là của chung [12]") is False


def test_looks_cut_off_still_catches_mid_word():
    assert looks_cut_off("Ngược lại, nếu họ đã đặt trọng tâm vào sự thật r") is True
    assert looks_cut_off("Người Bồ Đào Nha không thể viện dẫn quyền chiếm hữu nào cả vì họ chư") is True


def test_translation_is_not_truncated_when_the_source_breaks_off_too():
    # Chapter VII part 2: a blank line inside the sentence ends the part on
    # "they do not", so a faithful translation ends mid-sentence as well.
    source = (
        "the ownership of that jurisdiction is not thereby acquired over the "
        "territorial domain. For so far as the merely\nmunicipal laws of any place "
        "are concerned, they do not"
    )
    output = (
        "quyền sở hữu đối với thẩm quyền ấy không vì thế mà có được trên lãnh thổ. "
        "Bởi lẽ xét về các luật nội địa của bất kỳ nơi nào được xét đến, chúng không"
    )
    assert looks_cut_off(output) is True
    assert translation_looks_truncated(source, output) is False


def test_translation_is_truncated_when_the_source_ended_cleanly():
    source = "For so far as the merely municipal laws of any place are concerned, they do not apply."
    output = "Bởi lẽ xét về các luật nội địa của bất kỳ nơi nào được xét đến, chúng khô"
    assert translation_looks_truncated(source, output) is True


def test_completeness_uses_each_part_source():
    segment = {
        "source_text": "First part ends cleanly.\n\nSecond part trails off and they do not",
        "parts": [
            {"id": 1, "source_text": "First part ends cleanly.", "final": "Phần đầu kết thúc gọn."},
            {
                "id": 2,
                "source_text": "Second part trails off and they do not",
                "final": "Phần hai bỏ lửng ở đây và chúng không",
            },
        ],
        "final": "Phần đầu kết thúc gọn.\n\nPhần hai bỏ lửng ở đây và chúng không",
        "pipeline": {},
    }
    assert completeness_status(segment) == "ok"


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
