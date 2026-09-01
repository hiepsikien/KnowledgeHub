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
    assert text.replace("\n\n", "\n") == raw.strip()
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


def test_keeps_author_notes_drops_index_only():
    raw = (
        "*** START OF THE PROJECT GUTENBERG EBOOK DEMO ***\n\n"
        "CHAPTER I\n\n"
        + ("The argument proceeds with care and cites the ancients. " * 40)
        + "\n\nNOTES TO THE DEMO.\n\n"
        "[1] Pliny, Natural History, book two.\n\n"
        "INDEX.\n\n"
        "Aeneas, 12\nAchilles, 18\nApollo, 22\nAthens, 40\n"
        "Baldus, 44\nCicero, 50\nDutch, 61\nEast Indies, 70\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK DEMO ***\n"
        "Project Gutenberg License leftover\n"
    )
    text, report = normalize_manuscript(raw)
    assert report["family"] == "gutenberg"
    assert report["gutenberg"] is True
    assert report["dropped_tail_index"] is True
    assert report["kept_notes"] is True
    assert "Pliny, Natural History" in text
    assert "NOTES TO THE DEMO" in text
    assert "Achilles, 18" not in text
    assert "Project Gutenberg License leftover" not in text


def test_mid_chapter_footnotes_not_treated_as_tail():
    body = "CHAPTER I\n\n" + ("Discovery requires a method. " * 30) + "\n\nFOOTNOTES:\n\n[1] See Whewell.\n\n"
    body += "CHAPTER II\n\n" + ("The next step is classification. " * 30)
    raw = "*** START OF THE PROJECT GUTENBERG EBOOK DEMO ***\n\n" + body
    text, report = normalize_manuscript(raw)
    assert "CHAPTER II" in text
    assert "The next step is classification" in text
    assert report["dropped_tail_index"] is False


def test_index_stops_before_colon_footnotes():
    raw = (
        "*** START OF THE PROJECT GUTENBERG EBOOK DEMO ***\n\n"
        "CHAPTER I\n\n"
        + ("The argument proceeds with care and cites the ancients. " * 40)
        + "\n\nINDEX\n\n"
        "Aeneas, 12\nAchilles, 18\nApollo, 22\nAthens, 40\n"
        "Baldus, 44\nCicero, 50\nDutch, 61\nEast Indies, 70\n"
        "Xenophon, 90\n\n"
        "FOOTNOTES:\n\n"
        "[1] The eighth Section is omitted, the greater part of it consisting "
        "of verbal criticism upon Aristotle.\n\n"
        "Transcribers' Notes:\n\n"
        "Punctuation was made consistent.\n\n"
        "End of Project Gutenberg's Demo, by A. Author\n\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK DEMO ***\n"
        "Project Gutenberg License leftover\n"
    )
    text, report = normalize_manuscript(raw)
    assert report["dropped_tail_index"] is True
    assert report["kept_notes"] is True
    assert report["dropped_transcriber"] is True
    assert "eighth Section is omitted" in text
    assert "FOOTNOTES" in text
    assert "Achilles, 18" not in text
    assert "Transcribers" not in text
    assert "End of Project Gutenberg" not in text
    assert "Project Gutenberg License leftover" not in text


def test_archive_scan_drops_library_stamp():
    raw = (
        "THE BEAUTIFUL IN MUSIC\n\nCHAPTER I\n\n"
        + ("Form is the essence of musical beauty. " * 20)
        + "\n\nMusic\nLibrary\n\nML\n3847\n\nDATE DUE\n\nStanford University Libraries\nJUL 1 1970\n"
    )
    work = {"license": "public_domain_usa_archive", "source_url": "https://archive.org/details/x"}
    text, report = normalize_manuscript(raw, work=work)
    assert report["family"] == "archive_scan"
    assert report["dropped_library_stamp"] is True
    assert "Form is the essence" in text
    assert "DATE DUE" not in text
    assert "Music\nLibrary" not in text


def test_drops_tail_transcriber_and_publisher_ads():
    body = "CHAPTER I\n\n" + ("Discovery requires a method of observation. " * 80)
    ads = (
        "\n\nWORKS BY\n\nWILLIAM WHEWELL, D.D.\n\n"
        "HISTORY OF THE INDUCTIVE SCIENCES. Three Volumes, 24_s._\n"
        "NOVUM ORGANON RENOVATUM. 7_s._ 6_d._\n"
        "ELEMENTS OF MORALITY. Two Volumes, 15_s._\n"
        "LECTURES ON SYSTEMATIC MORALITY. 7_s._ 6_d._\n"
        "THE MECHANICAL EUCLID. 5_s._\n"
        "THE MECHANICS OF ENGINEERING. 9_s._\n"
        "THE DOCTRINE OF LIMITS. Octavo, 9_s._\n"
        "ASTRONOMICAL EXAMINATIONS. 5_s._\n"
        "CONIC SECTIONS. 5_s._ 6_d._\n"
        "ANALYTICAL STATICS. 7_s._ 6_d._\n"
        "Transcriber's Notes\n\nObvious typographical errors have been silently corrected.\n\n"
    )
    raw = (
        "*** START OF THE PROJECT GUTENBERG EBOOK DEMO ***\n\n"
        + body
        + ads
        + "*** END OF THE PROJECT GUTENBERG EBOOK DEMO ***\n"
    )
    text, report = normalize_manuscript(raw)
    assert report["dropped_publisher_ads"] is True
    assert report["dropped_transcriber"] is True
    assert "Discovery requires a method" in text
    assert "WORKS BY" not in text
    assert "24_s._" not in text
    assert "Transcriber" not in text


def test_drops_google_scan_boilerplate():
    raw = (
        "Google\n\nThis is a digital copy of a book that was preserved for generations "
        "on library shelves before it was carefully scanned by Google as part of a project "
        "to make the world's books discoverable online. Usage guidelines follow here. " * 12
        + "\nAbout Google Book Search\n\nat |http : //books . google . com/|\n\n"
        "THE BEAUTIFUL IN MUSIC\n\nCHAPTER I\n\n"
        + ("Form is the essence of musical beauty. " * 20)
        + "\n"
    )
    work = {"license": "public_domain_usa_archive", "source_url": "https://archive.org/details/x"}
    text, report = normalize_manuscript(raw, work=work)
    assert report["dropped_scan_boilerplate"] is True
    assert "THE BEAUTIFUL IN MUSIC" in text
    assert "digital copy of a book" not in text


def test_toc_stops_before_chapter_prose():
    raw = (
        "*** START OF THE PROJECT GUTENBERG EBOOK DEMO ***\n\n"
        "CONTENTS.\n\n"
        "CHAP. I. INTRODUCTION.\n"
        "CHAP. II. PLATO.\n"
        "CHAP. III. ARISTOTLE.\n"
        "CHAP. IV. THE ROMANS.\n"
        "CHAP. V. THE SCHOOLMEN.\n"
        "CHAP. VI. BACON.\n"
        "CHAP. VII. NEWTON.\n\n"
        "CHAPTER I.\n\n"
        "INTRODUCTION.\n\n"
        "By the examination of the elements of human thought in which I have\n"
        "been engaged, and by a consideration of the history of knowledge.\n\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK DEMO ***\n"
    )
    text, report = normalize_manuscript(raw)
    assert report["dropped_contents"] is True
    assert "CHAP. II. PLATO" not in text
    assert "CHAPTER I" in text
    assert "By the examination of the elements of human thought" in text


def test_named_page_column_toc_does_not_swallow_first_essay():
    raw = (
        "*** START OF THE PROJECT GUTENBERG EBOOK DISCOURSES ***\n\n"
        "CONTENTS.\n\n"
        "                                                      PAGE\n\n"
        "  Numbers; or, The Majority and the Remnant              1\n\n"
        "  Literature and Science                                72\n\n"
        "  Emerson                                              138\n\n\n"
        "  NUMBERS;\n"
        "  OR,\n"
        "  THE MAJORITY AND THE REMNANT.\n\n"
        "There is a characteristic saying of Dr. Johnson: Patriotism is the last\n"
        "refuge of a scoundrel, and it has in it something of plain robust sense.\n\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK DISCOURSES ***\n"
    )
    text, report = normalize_manuscript(raw)
    assert report["dropped_contents"] is True
    assert "Literature and Science                                72" not in text
    assert "NUMBERS;" in text
    assert "THE MAJORITY AND THE REMNANT." in text
    assert "characteristic saying of Dr. Johnson" in text


def test_short_lines_not_merged():
    raw = "Translated by\nFathers of the English Dominican Province\nNew York\n"
    text, report = normalize_manuscript(raw)
    assert report["unwrapped"] is False
    assert text.replace("\n\n", "\n") == "Translated by\nFathers of the English Dominican Province\nNew York"


def test_summa_file_if_present():
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
