from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextLine:
    index: int
    text: str
    start: int
    end: int
    blank_before: bool = False


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
                rows.append(
                    TextLine(
                        index=index,
                        text=stripped,
                        start=pos,
                        end=line_end,
                        blank_before=blank_before,
                    )
                )
                index += 1
            blank_before = False
        else:
            blank_before = True
        pos = line_end + 1
    return rows
