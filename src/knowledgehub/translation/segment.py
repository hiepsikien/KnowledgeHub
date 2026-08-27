from __future__ import annotations

import re

from ..grotius_extract import split_chapters as _split_grotius_chapters


def split_chapters(text: str) -> list[dict[str, str | int]]:
    chapters = _split_grotius_chapters(text)
    out: list[dict[str, str | int]] = []
    for num, body in chapters:
        out.append(
            {
                "chapter": num,
                "text": body,
                "words": chapter_word_count(body),
            }
        )
    return out


def chapter_word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def sample_segment(chapters: list[dict[str, str | int]], *, chapter: str = "I") -> dict[str, str | int]:
    for row in chapters:
        if row["chapter"] == chapter:
            return dict(row)
    raise KeyError(f"Chapter {chapter!r} not found")
