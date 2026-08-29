"""Post-parse structure: stanzas, play dialogue, heading merge."""

from __future__ import annotations

import re
from typing import Any

SPEAKER_CUE = re.compile(r"^[A-Z][A-Z\s,\.'-]{0,40}\.$")
STAGE_STRUCTURAL = re.compile(
    r"^(?:ACT|SCENE|CHAPTER|CHAP\.?|BOOK|PART|VOLUME|INTRODUCTION|PROLOGUE)\b",
    re.I,
)
DRAMATIS_MARKER = re.compile(r"Dramatis Personæ|DRAMATIS PERSON", re.I)
STAGE_DIRECTION = re.compile(
    r"^(?:Enter |Exit |Exeunt |Re-enter |Scene continues|\[Aside|\[Within|\[Coming|\[Exit)",
    re.I,
)
SCHOLASTIC_LIST = re.compile(r"^\(\d+\)\s+")
SCHOLASTIC_HEADING = re.compile(
    r"^(?:QUESTION\s+\d|(?:FIRST|SECOND|THIRD)\s+ARTICLE|Objection\s+\d)",
    re.I,
)
PLAY_MARKER = re.compile(r"Dramatis Personæ|DRAMATIS PERSON", re.I)
VI_VERSE_LINE = re.compile(r"^[À-ỹ0-9\s\[\],;—–-]{4,80}[,;]$")
METADATA_LINE = re.compile(
    r"^(?:"
    r"←(?:TỰA|\d+)$|"
    r".*→$|"
    r"\d{3,6}$|"
    r"\d{4,6}[A-Za-zÀ-ỹ].*|"
    r"\d+\s*—\s.*(?:dịch|của)\b|"
    r".*(?:Wikipedia|Wikidata|wiki khác|bài viết Wikipedia).*"
    r")",
    re.I,
)


def looks_like_play(text: str) -> bool:
    head = text[:8000]
    if PLAY_MARKER.search(head):
        return True
    cues = sum(1 for line in head.splitlines() if SPEAKER_CUE.match(line.strip()))
    return cues >= 4


def is_speaker_cue(line: str) -> bool:
    s = line.strip()
    if STAGE_STRUCTURAL.match(s):
        return False
    return bool(SPEAKER_CUE.match(s))


def is_stage_direction(line: str) -> bool:
    s = line.strip()
    return bool(STAGE_DIRECTION.match(s)) or (s.startswith("[") and s.endswith("]"))


def is_scholastic_list_item(line: str) -> bool:
    return bool(SCHOLASTIC_LIST.match(line.strip()))


def is_metadata_line(line: str) -> bool:
    return bool(METADATA_LINE.match(line.strip()))


def is_vi_verse_line(line: str) -> bool:
    s = line.strip()
    if not re.search(r"[À-ỹ]", s):
        return False
    if len(s) > 80 or len(s) < 4:
        return False
    if re.search(r"[.!?]$", s):
        return False
    return s.endswith(",") or s.endswith(";")


def is_indented_verse(*, indent: int, line: str) -> bool:
    s = line.strip()
    if indent >= 2 and len(s) < 120:
        if s.endswith(".") and len(s) > 60:
            return False
        return True
    return False


def group_dramatis_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge Dramatis Personæ cast list into one metadata block."""
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        text = str(block.get("text") or "")
        if block.get("type") == "paragraph" and DRAMATIS_MARKER.search(text):
            parts = [text]
            i += 1
            while i < len(blocks):
                nxt = blocks[i]
                if nxt.get("type") != "paragraph":
                    break
                line = str(nxt.get("text") or "").strip()
                if STAGE_STRUCTURAL.match(line):
                    break
                parts.append(str(nxt.get("text") or ""))
                i += 1
            out.append({"type": "metadata", "text": "\n".join(parts)})
            continue
        out.append(block)
        i += 1
    return out


def group_stanzas(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive verse_line blocks; stanza_start marks blank-line breaks."""
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block.get("type") != "verse_line":
            out.append(block)
            i += 1
            continue
        lines = [str(block.get("text") or "")]
        i += 1
        while i < len(blocks):
            nxt = blocks[i]
            if nxt.get("type") != "verse_line":
                break
            if nxt.get("stanza_start"):
                break
            lines.append(str(nxt.get("text") or ""))
            i += 1
        out.append({"type": "stanza", "text": "\n".join(lines), "lines": lines})
    return out


def merge_adjacent_headings(blocks: list[dict[str, Any]], *, max_level: int = 2) -> list[dict[str, Any]]:
    """Join consecutive short headings (e.g. Locke title page)."""
    if not blocks:
        return blocks
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block.get("type") != "heading":
            out.append(block)
            i += 1
            continue
        level = int(block.get("level") or 1)
        if level > max_level:
            out.append(block)
            i += 1
            continue
        parts = [str(block.get("text") or "")]
        lvl = level
        i += 1
        while i < len(blocks) and blocks[i].get("type") == "heading":
            nxt_lvl = int(blocks[i].get("level") or 1)
            nxt_text = str(blocks[i].get("text") or "")
            if nxt_lvl > max_level or len(nxt_text) > 90:
                break
            if SCHOLASTIC_HEADING.match(parts[0]) or SCHOLASTIC_HEADING.match(nxt_text):
                break
            parts.append(nxt_text)
            lvl = min(lvl, nxt_lvl)
            i += 1
        merged = " ".join(parts)
        if len(parts) > 1:
            out.append({"type": "heading", "text": merged, "level": lvl})
        else:
            out.append(block)
    return out


def scholastic_list_marker(inner: str) -> bool:
    return bool(re.fullmatch(r"\d+", inner.strip()))
