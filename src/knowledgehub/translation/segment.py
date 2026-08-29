from __future__ import annotations

import re

from ..grotius_extract import split_chapters as _split_grotius_chapters

CHAPTER_ROMAN = re.compile(r"(?m)^CHAPTER ([IVXLC]+)\.?\s*$")
GENERAL_HEADING = re.compile(
    r"(?m)^(?:(?:CHAPTER|CHAP\.?|Chapter|BOOK|VOLUME|PART)\s+([IVXLC]+|\d+)\.?|"
    r"(PREFACE|INTRODUCTION|PROLOGUE|EPILOGUE|APPENDIX))\s*$"
)


def chapter_word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def _unique_label(raw: str, used: dict[str, int]) -> str:
    base = re.sub(r"[^A-Za-z0-9]", "", raw)[:16] or "1"
    count = used.get(base, 0) + 1
    used[base] = count
    if count == 1:
        return base
    suffix = str(count)
    return f"{base[: 16 - len(suffix)]}{suffix}"


def _from_matches(text: str, matches: list[re.Match[str]]) -> list[dict[str, str | int]]:
    used: dict[str, int] = {}
    out: list[dict[str, str | int]] = []
    for index, match in enumerate(matches):
        raw = next((group for group in match.groups() if group), "1")
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        out.append(
            {
                "chapter": _unique_label(str(raw), used),
                "text": body,
                "words": chapter_word_count(body),
            }
        )
    return out


def split_chapters(text: str) -> list[dict[str, str | int]]:
    if CHAPTER_ROMAN.search(text):
        return [
            {"chapter": num, "text": body, "words": chapter_word_count(body)}
            for num, body in _split_grotius_chapters(text)
        ]
    general = _from_matches(text, list(GENERAL_HEADING.finditer(text)))
    if general:
        return general
    body = text.strip()
    if not body:
        raise ValueError("No text to split into chapters")
    return [{"chapter": "1", "text": body, "words": chapter_word_count(body)}]


def sample_segment(chapters: list[dict[str, str | int]], *, chapter: str | None = None) -> dict[str, str | int]:
    if not chapters:
        raise ValueError("No chapters to sample")
    if chapter:
        for row in chapters:
            if row["chapter"] == chapter:
                return dict(row)
        raise KeyError(f"Chapter {chapter!r} not found")
    return dict(chapters[0])
