from __future__ import annotations

from pathlib import Path

from knowledgehub.normalize import normalize_manuscript


SAMPLE = """The Project Gutenberg eBook of Demo

*** START OF THE PROJECT GUTENBERG EBOOK DEMO ***

Produced by A. Volunteer

ST. THOMAS AQUINAS

NOTE TO THIS ELECTRONIC EDITION

The text of this electronic edition was originally produced by Sandra
K. Perry. Italics are represented by underscores.

_______________________

CONTENTS

PROLOGUE

FIRST PART (QQ. 1-119)

Question

1.   The Nature and Extent of Sacred Doctrine
2.   The Existence of God

PROLOGUE

Because the doctor of Catholic truth ought not only to teach the
proficient, but also to instruct beginners.

*** END OF THE PROJECT GUTENBERG EBOOK DEMO ***

Project Gutenberg License leftover
"""


def test_strips_gutenberg_note_and_toc():
    text, report = normalize_manuscript(SAMPLE)
    assert report["gutenberg"] is True
    assert report["dropped_electronic_note"] is True
    assert report["dropped_contents"] is True
    assert "Project Gutenberg" not in text
    assert "NOTE TO THIS ELECTRONIC" not in text
    assert "The Nature and Extent" not in text
    assert text.startswith("ST. THOMAS AQUINAS")
    assert "Because the doctor of Catholic truth ought not only to teach the proficient" in text


def test_plain_text_unchanged():
    raw = "Of civil government.\n" * 20
    text, report = normalize_manuscript(raw)
    assert text == raw.strip()
    assert report["gutenberg"] is False
    assert report["dropped_contents"] is False


def test_aozora_ruby():
    raw = "吾輩《わがはい》は猫である。\n本文終わり\n底本：旧活字\n"
    text, report = normalize_manuscript(raw, language="ja")
    assert report["aozora"] is True
    assert "わがはい" not in text
    assert "猫である" in text
    assert "底本" not in text


def test_unwrap_keeps_headings():
    raw = (
        "Because the Master of Catholic Truth ought not only to teach the\n"
        "proficient, but also to instruct beginners.\n"
        "\n"
        "QUESTION 1\n"
        "\n"
        "THE NATURE AND EXTENT OF SACRED DOCTRINE\n"
        "\n"
        "Objection 1: It would seem that sacred doctrine is not necessary at all,\n"
        "because man can know the things he needs by natural reason alone.\n"
    )
    text, report = normalize_manuscript(raw)
    assert report["unwrapped"] is True
    assert "teach the proficient" in text
    assert "QUESTION 1" in text
    lines = text.split("\n")
    assert "QUESTION 1" in lines
    assert "Objection 1: It would seem that sacred doctrine is not necessary at all, because man" in text


def test_short_lines_not_merged():
    raw = "Translated by\nFathers of the English Dominican Province\nNew York\n"
    text, report = normalize_manuscript(raw)
    assert report["unwrapped"] is False
    assert text == "Translated by\nFathers of the English Dominican Province\nNew York"
    path = Path(__file__).resolve().parents[1] / "corpus/sources/aquinas/raw/summa_part1.txt"
    if not path.is_file():
        return
    raw = path.read_text(encoding="utf-8")
    text, report = normalize_manuscript(raw)
    assert report["gutenberg"] is True
    assert report["dropped_contents"] is True
    assert "Project Gutenberg Literary Archive Foundation" not in text
    assert "NOTE TO THIS ELECTRONIC EDITION" not in text
    assert "Because the Master of Catholic Truth ought not only to teach the proficient" in text
    assert "\nQUESTION 1\n" in text or "\n\nQUESTION 1\n" in text
    assert "FIRST ARTICLE [I, Q. 1, Art. 1]" in text
    assert report["unwrapped"] is True
    assert not text.lstrip().startswith("CONTENTS")
    assert "Roman transliteration" not in text[:4000]
    assert report["published_chars"] < report["source_chars"]
    assert report["published_chars"] > 1_000_000
