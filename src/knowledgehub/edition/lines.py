from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextLine:
    index: int
    text: str
    start: int
    end: int
    blank_before: bool = False
    indent: int = 0


_WIKI_JUNK = re.compile(
    r"^(?:"
    r"←(?:TỰA|\d+)$|"
    r".*→$|"
    r"\d{3,6}$|"
    r"\d{4,6}[A-Za-zÀ-ỹ].*|"
    r".*(?:Wikipedia|Wikidata|wiki khác|bài viết Wikipedia).*"
    r")",
    re.I,
)
_WIKI_NAV_SPLIT = re.compile(r"(?<=[A-ZÀ-Ỹ])([IVXLC]+\.)")


def is_wiki_junk_line(line: str) -> bool:
    return bool(_WIKI_JUNK.match(line.strip()))


def normalize_wiki_source(text: str) -> tuple[str, list[str]]:
    """Split Wikisource nav/metadata; return (body, apparatus lines)."""
    out: list[str] = []
    apparatus: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw.strip()
        if stripped and _WIKI_JUNK.match(stripped):
            apparatus.append(stripped)
            continue
        if stripped and "→" in stripped and _WIKI_NAV_SPLIT.search(stripped):
            parts = _WIKI_NAV_SPLIT.sub(r"\n\1", stripped).split("\n")
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if _WIKI_JUNK.match(part):
                    apparatus.append(part)
                else:
                    out.append(part)
            continue
        out.append(raw)
    return "\n".join(out), apparatus


def iter_lines(text: str) -> list[TextLine]:
    """Non-blank lines with source offsets."""
    rows: list[TextLine] = []
    pos = 0
    index = 0
    blank_before = True
    invisible = "\u200b\ufeff\u2060"
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line_end = pos + len(raw)
        stripped = raw.strip()
        if stripped:
            cleaned = stripped.strip(invisible)
            if cleaned:
                indent = len(raw) - len(raw.lstrip(" "))
                rows.append(
                    TextLine(
                        index=index,
                        text=stripped,
                        start=pos,
                        end=line_end,
                        blank_before=blank_before,
                        indent=indent,
                    )
                )
                index += 1
            blank_before = False
        else:
            blank_before = True
        pos = line_end + 1
    return rows
