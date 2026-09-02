"""Turn back-matter FOOTNOTES into Read glossary entries (tap-on-paragraph)."""

from __future__ import annotations

import re
from dataclasses import dataclass
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
FOOTNOTES_START = re.compile(r"(?im)^[ \t]*FOOTNOTES\s*[:.]?\s+")
NOTE_ITEM = re.compile(r"(?m)^\[(\d+)\]\s*")
NOTE_LINE = re.compile(r"^\[(\d+)\]\s*")
PG_FOOTNOTE_OPEN = re.compile(r"\[Footnote\s+(\d+)\s*:\s*", re.I)
STRUCT_HEAD = re.compile(
    r"^(?:CHAPTER|BOOK|VOLUME|PART)\s+[IVXLC\d]+[A-Z]?\s*\.?\s*(.*)$",
    re.I,
)
INDEX_HEAD = re.compile(r"^(?:INDEX|BIBLIOGRAPHY|CONTENTS)\s*[:.]?\s*$", re.I)
CHAPTER_KEY = re.compile(
    r"(?im)^(?:CHAPTER|BOOK|VOLUME|PART|Chapter)\s+([IVXLC\d]+[A-Z]?)\b"
)
TRANSCRIBER_TAIL = re.compile(
    r"(?im)^[ \t]*Transcriber(?:'?s|s'?)\s+Notes?\s*:?\s*$"
)
SPAN_NUMBERS = re.compile(r"\[(\d+(?:,\s*\d+)*)\]")
ROMAN = re.compile(r"^[IVXLCDM]+$", re.I)


@dataclass(frozen=True)
class FootnoteDump:
    start: int
    end: int
    body_start: int
    notes: dict[int, str]


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


def _is_structural_heading_line(line: str) -> bool:
    """True for a real CHAPTER/INDEX line, not wrap like 'CHAPTER III of the later volume.'"""
    s = line.strip()
    if not s:
        return False
    if INDEX_HEAD.match(s) or TRANSCRIBER_TAIL.match(s) or PG_END.search(s):
        return True
    match = STRUCT_HEAD.match(s)
    if not match:
        return False
    rest = match.group(1).strip()
    if not rest:
        return True
    if rest[0].islower():
        return False
    if len(s) > 90:
        return False
    letters = [ch for ch in rest if ch.isalpha()]
    if letters and rest.endswith(".") and sum(ch.islower() for ch in letters) / len(letters) > 0.3:
        return False
    return True


def _closing_bracket(text: str, open_at: int) -> int | None:
    depth = 1
    index = open_at + 1
    while index < len(text) and depth:
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        index += 1
    return index if depth == 0 else None


def _footnote_dump_end(text: str, after: int) -> int:
    """End offset of note items after a FOOTNOTES heading — not the next chapter heading."""
    pos = after
    saw_item = False
    blank_run = False
    end = after
    while pos < len(text):
        line_end = text.find("\n", pos)
        if line_end < 0:
            raw = text[pos:]
            next_pos = len(text)
        else:
            raw = text[pos:line_end]
            next_pos = line_end + 1
        stripped = raw.strip()
        if not stripped:
            blank_run = True
            pos = next_pos
            continue
        pg = PG_FOOTNOTE_OPEN.match(stripped)
        numbered = NOTE_LINE.match(stripped)
        if pg or numbered:
            if pg:
                open_at = pos + raw.find("[")
                closed = _closing_bracket(text, open_at)
                if closed is None:
                    return len(text)
                pos = closed
                if pos < len(text) and text[pos] == "\n":
                    pos += 1
                saw_item = True
                blank_run = False
                end = pos
                continue
            saw_item = True
            blank_run = False
            end = next_pos
            pos = next_pos
            continue
        if not saw_item:
            if _is_structural_heading_line(stripped) or FOOTNOTES_ONLY.match(stripped):
                return after
            pos = next_pos
            continue
        if (
            FOOTNOTES_ONLY.match(stripped)
            or _is_structural_heading_line(stripped)
            or PG_END.search(stripped)
            or TRANSCRIBER_TAIL.match(stripped)
        ):
            return pos
        if blank_run:
            return pos
        end = next_pos
        pos = next_pos
        blank_run = False
    return max(end, after)


def iter_footnote_dumps(text: str) -> list[FootnoteDump]:
    """Each FOOTNOTES dump with notes local to the preceding chapter body."""
    if not text.strip():
        return []
    dumps: list[FootnoteDump] = []
    body_start = 0
    for found in FOOTNOTES_ONLY.finditer(text):
        after = found.end()
        if not _looks_like_note_dump(text[after:]):
            continue
        end = _footnote_dump_end(text, after)
        if end <= found.start():
            continue
        notes = parse_footnote_blob(text[found.start() : end])
        if not notes:
            continue
        dumps.append(FootnoteDump(found.start(), end, body_start, notes))
        body_start = end
    return dumps


def footnote_dump_ranges(text: str) -> list[tuple[int, int]]:
    """Character ranges of per-chapter FOOTNOTES dumps (items only)."""
    return [(dump.start, dump.end) for dump in iter_footnote_dumps(text)]


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
    """Notes from a single FOOTNOTES dump (a chapter slice).

    Multiple dumps are not merged by number — that overwrites restarted [1], [2].
    Use ``iter_footnote_dumps`` for a whole book.
    """
    dumps = iter_footnote_dumps(text)
    if len(dumps) == 1:
        return dumps[0].notes
    return {}


def _span_numbers(marker: str) -> list[int]:
    match = SPAN_NUMBERS.fullmatch(str(marker or "").strip())
    if not match:
        return []
    return [int(part) for part in match.group(1).split(",")]


def _chapter_key(body: str) -> str:
    matches = list(CHAPTER_KEY.finditer(body))
    return matches[-1].group(1).upper() if matches else ""


def _block_text(block: dict[str, Any]) -> str:
    return str(block.get("text") or "").strip()


def _block_has_note_item(text: str) -> bool:
    if NOTE_LINE.match(text) or PG_FOOTNOTE_OPEN.search(text):
        return True
    return bool(FOOTNOTES_START.match(text) and re.search(r"\[\d+\]", text))


def _block_is_footnotes_heading(block: dict[str, Any]) -> bool:
    text = _block_text(block)
    if FOOTNOTES_ONLY.match(text):
        return True
    # Joined heading+first item: "FOOTNOTES: [75] P. 144."
    return bool(FOOTNOTES_START.match(text) and _block_has_note_item(text))


def _unclosed_pg_footnote(text: str) -> bool:
    index = 0
    while True:
        match = PG_FOOTNOTE_OPEN.search(text, index)
        if not match:
            return False
        closed = _closing_bracket(text, match.start())
        if closed is None:
            return True
        index = closed


def _dump_block_end(
    blocks: list[dict[str, Any]],
    heading_index: int,
    dump: FootnoteDump | None = None,
    source_text: str = "",
) -> int:
    """Exclusive end of dump blocks after a FOOTNOTES heading. heading_index if none.

    Prefer the source dump blob so wrap lines like ``CHAPTER III of the later
    volume.`` (often labeled heading) stay inside the dump, while the next
    real paragraph after a blank is kept.
    """
    if dump is not None and source_text:
        blob = _compact_note(source_text[dump.start : dump.end])
        if blob:
            cursor = heading_index
            search_from = 0
            saw_item = False
            while cursor < len(blocks):
                raw = _block_text(blocks[cursor])
                text = _compact_note(raw)
                if not text:
                    cursor += 1
                    continue
                found = blob.find(text, search_from)
                if found < 0 and search_from:
                    found = blob.find(text)
                if found < 0:
                    break
                if _block_has_note_item(raw):
                    saw_item = True
                search_from = found + max(len(text), 1)
                cursor += 1
                if search_from >= len(blob):
                    break
            if saw_item and cursor > heading_index:
                return cursor
    cursor = heading_index + 1
    saw_item = False
    blank_run = False
    acc = ""
    end = heading_index
    while cursor < len(blocks):
        text = _block_text(blocks[cursor])
        if not text:
            blank_run = True
            cursor += 1
            continue
        pg_open = _unclosed_pg_footnote(acc)
        if _block_has_note_item(text) or pg_open:
            saw_item = True
            blank_run = False
            acc += "\n" + text
            end = cursor + 1
            cursor += 1
            continue
        if not saw_item:
            if _is_structural_heading_line(text) or FOOTNOTES_ONLY.match(text):
                return heading_index
            cursor += 1
            continue
        if (
            FOOTNOTES_ONLY.match(text)
            or _is_structural_heading_line(text)
            or TRANSCRIBER_TAIL.match(text)
        ):
            break
        if blank_run:
            break
        acc += "\n" + text
        end = cursor + 1
        cursor += 1
        blank_run = False
    return end if saw_item else heading_index


def _apply_notes_to_blocks(
    blocks: list[dict[str, Any]],
    notes: dict[int, str],
) -> list[dict[str, Any]]:
    if not notes:
        return blocks
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
                bodies = [notes[number] for number in _span_numbers(row.get("text") or "") if number in notes]
                if bodies:
                    row["note"] = " ".join(bodies)[:8000]
            new_spans.append(row)
        out.append({**block, "spans": new_spans})
    return out


def note_entries_from_parsed(
    parsed: dict[int, str],
    *,
    body: str = "",
    chapter: str = "",
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
                "chapter": chapter,
            }
        )
    return entries


def notes_for_chapter_blocks(
    blocks: list[dict[str, Any]],
    catalog: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Notes already attached to these blocks; catalog is a fallback only."""
    from_spans: dict[str, dict[str, Any]] = {}
    markers: set[str] = set()
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
                    "chapter": str(span.get("chapter") or ""),
                }
    if from_spans:
        return [from_spans[key] for key in sorted(from_spans, key=lambda marker: _span_numbers(marker) or [0])]
    if catalog:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in catalog:
            marker = str(row.get("marker") or "")
            if marker in markers and row.get("body"):
                grouped.setdefault(marker, []).append(row)
        # Book-wide catalog cannot choose among restarted [1] per chapter.
        return [
            rows[0]
            for marker, rows in sorted(grouped.items(), key=lambda item: _span_numbers(item[0]) or [0])
            if len(rows) == 1
        ]
    return []


def attach_footnote_bodies(
    blocks: list[dict[str, Any]],
    source_text: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach each dump to the preceding body and drop FOOTNOTES blocks from reading flow."""
    dumps = iter_footnote_dumps(source_text) if source_text else []
    dump_index = 0
    pending: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    catalog: list[dict[str, Any]] = []

    def flush(notes: dict[int, str]) -> None:
        nonlocal pending
        body = "\n\n".join(_block_text(block) for block in pending)
        applied = _apply_notes_to_blocks(pending, notes)
        out.extend(applied)
        catalog.extend(note_entries_from_parsed(notes, body=body, chapter=_chapter_key(body)))
        pending = []

    index = 0
    while index < len(blocks):
        if _block_is_footnotes_heading(blocks[index]):
            dump = dumps[dump_index] if dump_index < len(dumps) else None
            dump_end = _dump_block_end(blocks, index, dump, source_text)
            if dump_end > index:
                if dump_index < len(dumps):
                    notes = dumps[dump_index].notes
                    dump_index += 1
                else:
                    blob = "\n\n".join(_block_text(block) for block in blocks[index:dump_end])
                    notes = parse_footnote_blob(blob)
                flush(notes)
                index = dump_end
                continue
        pending.append(blocks[index])
        index += 1
    if dumps and dump_index < len(dumps) and pending:
        flush(dumps[dump_index].notes)
        dump_index += 1
    else:
        out.extend(pending)
    while dump_index < len(dumps):
        catalog.extend(
            note_entries_from_parsed(
                dumps[dump_index].notes,
                body=source_text[dumps[dump_index].body_start : dumps[dump_index].start],
                chapter=_chapter_key(source_text[dumps[dump_index].body_start : dumps[dump_index].start]),
            )
        )
        dump_index += 1
    return out, catalog


def notes_for_read_publish(
    edition: dict[str, Any],
    *,
    chapters: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Flatten REF notes / span.note into the Hub→Read ``notes[]`` shape.

    Prefers per-chapter ``notes`` (and footnote spans) so numbering that restarts
    each chapter stays scoped. Falls back to edition-level ``notes``.
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(row: dict[str, Any], *, chapter: str = "") -> None:
        body = str(row.get("body") or "").strip()
        marker = str(row.get("marker") or "").strip()
        if not body:
            return
        if marker and not FOOTNOTE_MARKER.fullmatch(marker):
            marker = ""
        anchor = str(row.get("anchor") or "").strip()
        chapter_id = str(row.get("chapter") or chapter or "").strip()
        label = str(row.get("label") or row.get("name") or "").strip()
        if not label:
            label = f"{anchor} {marker}".strip() if anchor and marker else (marker or anchor)
        if not label:
            return
        key = (marker or label, chapter_id, body[:80])
        if key in seen:
            return
        seen.add(key)
        out.append(
            {
                "id": str(row.get("id") or ""),
                "kind": str(row.get("kind") or "footnote"),
                "label": label[:300],
                "marker": marker,
                "anchor": anchor[:300],
                "chapter": chapter_id,
                "body": body[:8000],
                "group_label": str(row.get("group_label") or "Chú thích"),
            }
        )

    for chapter in chapters or []:
        chapter_id = str(chapter.get("chapter_id") or chapter.get("id") or "")
        for row in chapter.get("notes") or []:
            add(row, chapter=chapter_id)
        for block in chapter.get("blocks") or []:
            for span in block.get("spans") or []:
                if span.get("style") != "footnote" or not span.get("note"):
                    continue
                add(
                    {
                        "marker": span.get("text") or "",
                        "body": span.get("note") or "",
                        "chapter": chapter_id,
                        "kind": "footnote",
                    },
                    chapter=chapter_id,
                )

    if out:
        return out

    for row in edition.get("notes") or []:
        add(row)
    for block in edition.get("blocks") or []:
        for span in block.get("spans") or []:
            if span.get("style") != "footnote" or not span.get("note"):
                continue
            add(
                {
                    "marker": span.get("text") or "",
                    "body": span.get("note") or "",
                    "chapter": span.get("chapter") or "",
                    "kind": "footnote",
                }
            )
    return out


def glossary_from_footnotes(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (body without FOOTNOTES dumps, glossary entries for Read)."""
    dumps = iter_footnote_dumps(text)
    if not dumps:
        return text, []
    stripped = _cut_ranges(text, [(dump.start, dump.end) for dump in dumps])
    entries: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for dump in dumps:
        chapter_body = text[dump.body_start : dump.start]
        chapter = _chapter_key(chapter_body)
        for number, summary in sorted(dump.notes.items()):
            marker = f"[{number}]"
            name = _anchor_name(chapter_body, number)
            label = f"{name} {marker}" if name != marker else marker
            if label in used_names and chapter:
                label = f"{label} (ch. {chapter})"
            used_names.add(label)
            entries.append(
                {
                    "name": label[:300],
                    "aliases": [marker],
                    "summary": summary[:8000],
                    "group_label": "Chú thích",
                    "kind": "footnote",
                    "marker": marker,
                    "anchor": name[:300],
                    "chapter": chapter,
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
