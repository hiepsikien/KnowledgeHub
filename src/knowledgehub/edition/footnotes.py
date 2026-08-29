"""Turn back-matter FOOTNOTES into Read glossary entries (tap-on-paragraph)."""

from __future__ import annotations

import re
from typing import Any

from .profile import PG_END

KIND_LABEL = {
    "footnote": "Chú thích",
    "glossary": "Thuật ngữ",
    "context": "Bối cảnh",
    "term": "Thuật ngữ",
}
KIND_ALIASES = {"term": "glossary"}
FOOTNOTE_MARKER = re.compile(r"^\[\d+\]$")

FOOTNOTES_ONLY = re.compile(r"(?im)^[ \t]*FOOTNOTES\s*[:.]?\s*$")
NOTE_ITEM = re.compile(r"(?m)^\[(\d+)\]\s*")
ROMAN = re.compile(r"^[IVXLCDM]+$", re.I)


def annotation_kind(item: dict[str, Any]) -> str:
    raw = str(item.get("kind") or "footnote").strip().lower()
    kind = KIND_ALIASES.get(raw, raw)
    return kind if kind in {"footnote", "glossary", "context"} else "footnote"


def glossary_term_key(item: dict[str, Any]) -> str:
    raw = str(item.get("anchor_text") or item.get("title_vi") or item.get("marker") or "")
    return re.sub(r"\s+", " ", raw).casefold().strip()


def annotation_label(item: dict[str, Any]) -> str:
    kind = annotation_kind(item)
    marker = str(item.get("marker") or "").strip()
    anchor = str(item.get("anchor_text") or "").strip()
    title = str(item.get("title_vi") or "").strip()
    if kind == "footnote":
        if anchor and FOOTNOTE_MARKER.fullmatch(marker) and marker not in anchor:
            return f"{anchor} {marker}"[:300]
        return (anchor or title or marker or "Chú thích")[:300]
    return (title or anchor or KIND_LABEL[kind])[:300]


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
        label = f"{name} {marker}" if name != marker else marker
        entries.append(
            {
                "name": label[:300],
                "aliases": [marker],
                "summary": summary[:8000],
                "group_label": "Chú thích",
                "kind": "footnote",
                "marker": marker,
                "anchor": name[:300],
                "chapter": "",
            }
        )
    return body, entries


def notes_from_annotations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Canonical reader notes: unique labels, one glossary term, marker-only match keys."""
    notes: list[dict[str, Any]] = []
    seen_glossary: set[str] = set()
    for item in items:
        body = str(item.get("body_vi") or item.get("body") or "").strip()
        if not body:
            continue
        kind = annotation_kind(item)
        marker = str(item.get("marker") or "").strip()
        if kind == "glossary":
            marker = ""
        elif not FOOTNOTE_MARKER.fullmatch(marker):
            marker = ""
        anchor = str(item.get("anchor_text") or "").strip()
        label = annotation_label({**item, "kind": kind, "marker": marker})
        if not label:
            continue
        if kind == "glossary":
            key = glossary_term_key({"anchor_text": anchor or label})
            if not key or key in seen_glossary:
                continue
            seen_glossary.add(key)
        aliases: list[str] = []
        if marker and marker != label:
            aliases.append(marker)
        elif kind != "footnote" and anchor and anchor != label:
            aliases.append(anchor)
        notes.append(
            {
                "id": str(item.get("id") or ""),
                "kind": kind,
                "label": label[:300],
                "marker": marker,
                "anchor": anchor[:300],
                "chapter": str(item.get("chapter") or ""),
                "body": body[:8000],
                "group_label": KIND_LABEL[kind],
                "aliases": aliases,
            }
        )
    return notes


def glossary_row_from_note(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(note.get("label") or note.get("name") or "")[:300],
        "aliases": list(note.get("aliases") or []),
        "summary": str(note.get("body") or note.get("summary") or "")[:8000],
        "group_label": str(note.get("group_label") or KIND_LABEL.get(str(note.get("kind") or ""), "Chú thích")),
        "kind": str(note.get("kind") or "footnote"),
        "marker": str(note.get("marker") or ""),
        "anchor": str(note.get("anchor") or ""),
        "chapter": str(note.get("chapter") or ""),
    }


def glossary_from_annotations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [glossary_row_from_note(note) for note in notes_from_annotations(items)]


def merge_glossary(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for row in group:
            key = (row.get("name") or "") + "|" + "|".join(row.get("aliases") or [])
            merged[key] = row
    return list(merged.values())
