from __future__ import annotations

from knowledgehub.grotius_extract import extract_english_treatise, split_chapters

SAMPLE_BILINGUAL = """
CHAPTER I

_By the Law of Nations navigation is free to all persons whatsoever_

My intention is to demonstrate briefly and clearly that the
Dutch have the right to sail to the East Indies.

- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

Hoc igitur qui tollunt, illam laudatissimam tollunt humani generis
societatem, naturam denique ipsam violant.

- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

Those therefore who deny this law, destroy this most praise-worthy
bond of human fellowship, remove the opportunities for doing a kindness.

CHAPTER II

_That the Portuguese have no right to the sovereignty of the Indian seas_

The Portuguese claim rests upon discovery and Papal donation.
"""


def test_extract_english_skips_latin_blocks():
    body, stats = extract_english_treatise(SAMPLE_BILINGUAL)
    assert stats["chapters"] == 2
    assert stats["latin_blocks_skipped"] >= 1
    assert "Hoc igitur" not in body
    assert "My intention is to demonstrate" in body
    assert "Those therefore who deny this law" in body
    assert "CHAPTER II" in body


def test_split_chapters():
    body, _ = extract_english_treatise(SAMPLE_BILINGUAL)
    chapters = split_chapters(body)
    assert [n for n, _ in chapters] == ["I", "II"]
    assert "Indian seas" in chapters[1][1]
