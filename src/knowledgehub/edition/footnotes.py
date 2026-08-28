"""Turn back-matter FOOTNOTES into Read glossary entries (tap-on-paragraph)."""

from __future__ import annotations

import re
from typing import Any

from .profile import PG_END

KIND_LABEL = {
    "footnote": "Chú thích",
    "glossary": "Thuật ngữ",
    "context": "Bối cảnh",
}

FOOTNOTES_ONLY = re.compile(r"(?im)^[ \t]*FOOTNOTES\s*[:.]?\s*$")
NOTE_ITEM = re.compile(r"(?m)^\[(\d+)\]\s*")
ROMAN = re.compile(r"^[IVXLCDM]+$", re.I)


def _anchor_name(body: str, number: int) -> str:
    pattern = re.compile(
        rf"([A-ZÀ-Ỵ][\wÀ-ỹ.'’\-]{{1,40}})\.?,?\s*\[{number}\]"
    )
    fallback = f"[{number}]"
    matches = list(pattern.finditer(body))
    for match in reversed(matches):
        name = match.group(1).strip(" .,'’")
        if len(name) < 3 or ROMAN.fullmatch(name):
            continue
        return name
    return fallback


def split_footnotes_section(text: str) -> tuple[str, str]:
    """Cut only a tail FOOTNOTES dump, not NOTES TO … essays."""
    match = None
    for found in FOOTNOTES_ONLY.finditer(text):
        if found.start() >= int(len(text) * 0.4):
            match = found
    if match is None:
        return text, ""
    end = len(text)
    pg = PG_END.search(text, match.start())
    if pg:
        end = pg.start()
    trans = re.search(r"(?im)^[ \t]*Transcriber(?:'?s|s'?)\s+Notes?\s*:?\s*$", text[match.start() :])
    if trans:
        end = min(end, match.start() + trans.start())
    return text[: match.start()].rstrip(), text[match.start() : end]


def parse_numbered_notes(blob: str) -> dict[int, str]:
    parts = NOTE_ITEM.split(blob)
    if len(parts) < 3:
        return {}
    items: dict[int, str] = {}
    numbered = parts[1:]
    for i in range(0, len(numbered) - 1, 2):
        number = int(numbered[i])
        body = re.sub(r"\s+", " ", numbered[i + 1]).strip()
        if len(body) >= 8:
            items[number] = body
    return items


def glossary_from_footnotes(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (body without FOOTNOTES dump, glossary entries for Read)."""
    body, notes_blob = split_footnotes_section(text)
    parsed = parse_numbered_notes(notes_blob)
    if not parsed:
        return text, []
    entries: list[dict[str, Any]] = []
    for number, summary in sorted(parsed.items()):
        marker = f"[{number}]"
        name = _anchor_name(body, number)
        aliases = [marker]
        entries.append(
            {
                "name": name[:300],
                "aliases": aliases,
                "summary": summary[:8000],
                "group_label": "Chú thích",
            }
        )
    return body, entries


def glossary_from_annotations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("anchor_text") or item.get("title_vi") or item.get("marker") or "").strip()
        summary = str(item.get("body_vi") or item.get("body") or "").strip()
        if not name or not summary:
            continue
        marker = str(item.get("marker") or "").strip()
        aliases = [marker] if marker and marker != name else []
        kind = str(item.get("kind") or "footnote")
        out.append(
            {
                "name": name[:300],
                "aliases": aliases,
                "summary": summary[:8000],
                "group_label": KIND_LABEL.get(kind, "Chú thích"),
            }
        )
    return out


def merge_glossary(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for row in group:
            key = (row.get("name") or "") + "|" + "|".join(row.get("aliases") or [])
            merged[key] = row
    return list(merged.values())
