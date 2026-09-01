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
PG_FOOTNOTE_OPEN = re.compile(r"\[Footnote\s+(\d+)\s*:\s*", re.I)
DUMP_NEXT_BOUND = re.compile(
    r"(?im)^(?:CHAPTER|BOOK|VOLUME|PART)\s+[IVXLC\d]+\b"
    r"|^INDEX\s*[:.]?\s*$"
    r"|^BIBLIOGRAPHY\s*[:.]?\s*$"
    r"|^CONTENTS\s*\.?$"
)
TRANSCRIBER_TAIL = re.compile(
    r"(?im)^[ \t]*Transcriber(?:'?s|s'?)\s+Notes?\s*:?\s*$"
)
SPAN_NUMBERS = re.compile(r"\[(\d+(?:,\s*\d+)*)\]")
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


def _compact_note(body: str) -> str:
    return re.sub(r"\s+", " ", body).strip()


def _looks_like_note_dump(window: str) -> bool:
    """True when a FOOTNOTES heading is followed by real note items, not a TOC row."""
    sample = window[:1200]
    if PG_FOOTNOTE_OPEN.search(sample):
        return True
    return bool(NOTE_ITEM.search(sample))


def footnote_dump_ranges(text: str) -> list[tuple[int, int]]:
    """Character ranges of per-chapter (or tail) FOOTNOTES dumps."""
    headings = list(FOOTNOTES_ONLY.finditer(text))
    ranges: list[tuple[int, int]] = []
    for index, found in enumerate(headings):
        after = found.end()
        if not _looks_like_note_dump(text[after:]):
            continue
        end = len(text)
        if index + 1 < len(headings):
            end = min(end, headings[index + 1].start())
        bound = DUMP_NEXT_BOUND.search(text, after)
        if bound:
            end = min(end, bound.start())
        pg = PG_END.search(text, after)
        if pg:
            end = min(end, pg.start())
        trans = TRANSCRIBER_TAIL.search(text, after)
        if trans:
            end = min(end, trans.start())
        if end > found.start():
            ranges.append((found.start(), end))
    return ranges


def _cut_ranges(text: str, ranges: list[tuple[int, int]]) -> str:
    if not ranges:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end in ranges:
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts).rstrip()


def split_footnotes_section(text: str) -> tuple[str, str]:
    """Cut FOOTNOTES dumps (every chapter, not only the book tail)."""
    ranges = footnote_dump_ranges(text)
    if not ranges:
        return text, ""
    blob = "\n\n".join(text[start:end] for start, end in ranges)
    return _cut_ranges(text, ranges), blob


def parse_gutenberg_bracket_notes(blob: str) -> dict[int, str]:
    """Parse Gutenberg ``[Footnote 12: body]`` items, including wrapped lines."""
    items: dict[int, str] = {}
    for match in PG_FOOTNOTE_OPEN.finditer(blob):
        depth = 1
        index = match.start() + 1
        while index < len(blob) and depth:
            char = blob[index]
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
            index += 1
        if depth != 0:
            continue
        body = _compact_note(blob[match.end() : index - 1])
        if len(body) >= 2:
            items[int(match.group(1))] = body
    return items


def parse_numbered_notes(blob: str) -> dict[int, str]:
    parts = NOTE_ITEM.split(blob)
    if len(parts) < 3:
        return {}
    items: dict[int, str] = {}
    numbered = parts[1:]
    for i in range(0, len(numbered) - 1, 2):
        number = int(numbered[i])
        body = _compact_note(numbered[i + 1])
        body = PG_FOOTNOTE_OPEN.split(body, maxsplit=1)[0].strip()
        if len(body) >= 2:
            items[number] = body
    return items


def parse_footnote_blob(blob: str) -> dict[int, str]:
    """Numbered ``[1]`` notes plus Gutenberg ``[Footnote 1: …]`` notes."""
    items = parse_numbered_notes(blob)
    items.update(parse_gutenberg_bracket_notes(blob))
    return items


def notes_from_text(text: str) -> dict[int, str]:
    """Map footnote numbers to bodies from FOOTNOTES dumps in chapter or book text."""
    if not text.strip():
        return {}
    ranges = footnote_dump_ranges(text)
    if not ranges:
        return {}
    parsed: dict[int, str] = {}
    for start, end in ranges:
        parsed.update(parse_footnote_blob(text[start:end]))
    return parsed


def _span_numbers(marker: str) -> list[int]:
    match = SPAN_NUMBERS.fullmatch(str(marker or "").strip())
    if not match:
        return []
    return [int(part) for part in match.group(1).split(",")]


def notes_from_blocks(blocks: list[dict[str, Any]]) -> dict[int, str]:
    texts = [str(block.get("text") or "") for block in blocks]
    return notes_from_text("\n\n".join(texts))


def note_entries_from_parsed(
    parsed: dict[int, str],
    *,
    body: str = "",
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for number, summary in sorted(parsed.items()):
        marker = f"[{number}]"
        name = _anchor_name(body, number) if body else marker
        entries.append(
            {
                "marker": marker,
                "body": summary[:8000],
                "anchor": "" if name == marker else name[:300],
            }
        )
    return entries


def notes_for_chapter_blocks(
    blocks: list[dict[str, Any]],
    catalog: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Notes whose markers appear in these blocks, preferring the chapter catalog."""
    markers: set[str] = set()
    from_spans: dict[str, dict[str, Any]] = {}
    for block in blocks:
        for span in block.get("spans") or []:
            if span.get("style") != "footnote":
                continue
            marker = str(span.get("text") or "")
            if not marker:
                continue
            markers.add(marker)
            if span.get("note"):
                from_spans[marker] = {
                    "marker": marker,
                    "body": str(span.get("note") or "")[:8000],
                    "anchor": "",
                }
    if catalog:
        filtered = [row for row in catalog if row.get("marker") in markers and row.get("body")]
        if filtered:
            return filtered
    return [from_spans[key] for key in sorted(from_spans, key=lambda marker: _span_numbers(marker) or [0])]


def attach_footnote_bodies(
    blocks: list[dict[str, Any]],
    source_text: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Copy FOOTNOTES dump bodies onto inline ``[n]`` spans."""
    parsed = notes_from_text(source_text)
    if not parsed:
        parsed = notes_from_blocks(blocks)
    if not parsed:
        return blocks, []
    body = source_text or "\n\n".join(str(block.get("text") or "") for block in blocks)
    notes = note_entries_from_parsed(parsed, body=body)
    out: list[dict[str, Any]] = []
    for block in blocks:
        spans = block.get("spans")
        if not spans:
            out.append(block)
            continue
        new_spans: list[dict[str, Any]] = []
        for span in spans:
            row = dict(span)
            if row.get("style") == "footnote":
                bodies = [parsed[number] for number in _span_numbers(row.get("text") or "") if number in parsed]
                if bodies:
                    row["note"] = " ".join(bodies)[:8000]
            new_spans.append(row)
        out.append({**block, "spans": new_spans})
    return out, notes


def glossary_from_footnotes(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (body without FOOTNOTES dumps, glossary entries for Read)."""
    body, notes_blob = split_footnotes_section(text)
    parsed = parse_footnote_blob(notes_blob) if notes_blob else {}
    if not parsed:
        return text, []
    stripped = body
    entries: list[dict[str, Any]] = []
    for number, summary in sorted(parsed.items()):
        marker = f"[{number}]"
        name = _anchor_name(stripped, number)
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
    return stripped, entries


def notes_from_annotations(
    items: list[dict[str, Any]],
    *,
    chapter_texts: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Canonical reader notes: unique labels, one glossary term, marker-only match keys."""
    notes: list[dict[str, Any]] = []
    seen_glossary: set[str] = set()
    footnotes = [item for item in items if annotation_kind(item) == "footnote"]
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
        if kind != "footnote":
            chapter = str(item.get("chapter") or "")
            text = ""
            if chapter_texts:
                text = chapter_texts.get(chapter) or chapter_texts.get(chapter.upper()) or ""
            if extra_covered_by_footnote(item, footnotes, text):
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


def extra_covered_by_footnote(
    extra: dict[str, Any],
    footnotes: list[dict[str, Any]],
    chapter_text: str = "",
) -> bool:
    """True when a Hub extra restates a book footnote already on that phrase."""
    anchor = str(extra.get("anchor_text") or extra.get("anchor") or extra.get("title_vi") or "").strip()
    if len(anchor) < 4:
        return False
    key = re.sub(r"\s+", " ", anchor).casefold()
    if len(key) < 6:
        return False
    chapter = str(extra.get("chapter") or "").strip().upper()
    covering = _markers_covering_anchor(chapter_text, anchor) if chapter_text else set()
    for item in footnotes:
        if chapter and str(item.get("chapter") or "").strip().upper() not in {"", chapter}:
            continue
        title = _folded_blob(
            item.get("anchor_text") or item.get("anchor"),
            item.get("title_vi") or item.get("label"),
        )
        if key in title:
            return True
        marker = str(item.get("marker") or "").strip()
        if marker and marker in covering:
            body = _folded_blob(item.get("body_vi") or item.get("body"))
            if key in body:
                return True
    return False


def _folded_blob(*parts: Any) -> str:
    return re.sub(r"\s+", " ", " ".join(str(part or "") for part in parts)).casefold()


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"[.!?\n]+", text):
        if match.start() > start:
            spans.append((start, match.start()))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _markers_covering_anchor(text: str, anchor: str) -> set[str]:
    found: set[str] = set()
    if not text or not anchor:
        return found
    for match in re.finditer(re.escape(anchor), text, flags=re.IGNORECASE):
        after = text[match.end() : match.end() + 32]
        before = text[max(0, match.start() - 16) : match.start()]
        for nearby in re.finditer(r"\[\d+\]", f"{before} {after}"):
            found.add(nearby.group(0))
        for start, end in _sentence_spans(text):
            if start <= match.start() < end:
                for nearby in re.finditer(r"\[\d+\]", text[start:end]):
                    found.add(nearby.group(0))
                break
    return found


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


def glossary_from_annotations(
    items: list[dict[str, Any]],
    *,
    chapter_texts: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    return [
        glossary_row_from_note(note)
        for note in notes_from_annotations(items, chapter_texts=chapter_texts)
    ]


def merge_glossary(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for row in group:
            key = (row.get("name") or "") + "|" + "|".join(row.get("aliases") or [])
            merged[key] = row
    return list(merged.values())
