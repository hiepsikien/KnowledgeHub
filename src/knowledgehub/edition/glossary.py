"""Book-back Glossary chapters → Read term cards and resolved footnotes."""

from __future__ import annotations

import re
from typing import Any

from .footnotes import KIND_LABEL, glossary_row_from_note, merge_glossary

GUTENBERG_STRONG = re.compile(r"~([^~\n]+?)~")
ENTRY_START = re.compile(r"(?m)^[ \t]*~([^~\n]{1,80})~")
GLOSSARY_TITLE = re.compile(
    r"^(?:the\s+)?(?:glossary|bảng chú giải|glossaire|glossar)\b",
    re.I,
)
SEE_GLOSSARY = re.compile(
    r"(?is)^\s*(?:see\s+glossary|xem\s+bảng\s+chú\s+giải)"
    r"(?:\s*[,:]\s*|\s+)?"
    r"(?:[\"“«]\s*(?P<quoted>.+?)\s*[\"”»])?"
    r"\s*\.?\s*$"
)
SEE_PAGE = re.compile(r"(?i)^p\.?\s*\d")
OR_ALIAS = re.compile(r"^,\s*or\s+([^,]+?)(?=,\s|$)", re.I)
EQUALS_ALIAS = re.compile(r"^\s*=\s*([^,\n]+)")
NOT_TITLE_START = re.compile(
    r"^(?:is|was|are|were|a|an|consisting|having|meaning|which|that|who|whose|this|these|those)\b",
    re.I,
)
SHORT_SEE_ALSO = re.compile(
    r"(?is)^(?P<head>.{1,80}?\.)\s*See\s+(?P<target>[^.]+)\.?\s*$"
)


def is_glossary_chapter(chapter: dict[str, Any]) -> bool:
    fields = [
        str(chapter.get(key) or "").strip()
        for key in ("title", "ref_title", "name")
    ]
    if any(GLOSSARY_TITLE.search(field) for field in fields if field):
        return True
    kind = str(chapter.get("kind") or "").strip().lower()
    blob = " ".join(fields).casefold()
    return kind in {"glossary", "back_matter"} and "glossary" in blob


def parse_glossary_entries(text: str, *, chapter: str = "") -> list[dict[str, Any]]:
    """Split a Gutenberg Glossary chapter (`~Term~` heads) into term cards."""
    if not text or not ENTRY_START.search(text):
        return []
    matches = list(ENTRY_START.finditer(text))
    entries: list[dict[str, Any]] = []
    seen_names: dict[str, int] = {}
    for index, found in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        row = _parse_entry_chunk(text[found.start() : end], chapter=chapter)
        if not row:
            continue
        key = _fold(row["name"])
        count = seen_names.get(key, 0)
        seen_names[key] = count + 1
        if count:
            hint = _disambiguator(row["summary"], row["name"])
            if hint:
                row["name"] = f"{row['name']} ({hint})"[:300]
        entries.append(row)
    _resolve_see_also(entries)
    return entries


def glossary_entries_from_chapters(chapters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for chapter in chapters or []:
        if not is_glossary_chapter(chapter):
            continue
        chapter_id = str(chapter.get("chapter_id") or chapter.get("id") or "").strip()
        text = str(chapter.get("reading_markdown") or chapter.get("content") or "").strip()
        if not ENTRY_START.search(text):
            text = _text_from_blocks(chapter.get("blocks") or [])
        entries.extend(parse_glossary_entries(text, chapter=chapter_id))
    return entries


def lookup_glossary_entry(
    query: str,
    entries: list[dict[str, Any]],
    *,
    skip: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    needle = _fold(query)
    if len(needle) < 3:
        return None
    exact: list[dict[str, Any]] = []
    prefix: list[dict[str, Any]] = []
    for entry in entries:
        if skip is not None and entry is skip:
            continue
        for label in _labels(entry):
            folded = _fold(label)
            if not folded:
                continue
            if folded == needle:
                exact.append(entry)
                break
            shorter, longer = (folded, needle) if len(folded) <= len(needle) else (needle, folded)
            if len(shorter) >= 8 and longer.startswith(shorter):
                prefix.append(entry)
                break
    picked = _unique(exact) or _unique(prefix)
    return picked[0] if len(picked) == 1 else None


def infer_glossary_entry(host_text: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    host = _fold(host_text)
    if len(host) < 4:
        return None
    hits: list[tuple[int, dict[str, Any]]] = []
    for entry in entries:
        best = 0
        for label in _labels(entry):
            folded = _fold(label)
            if len(folded) >= 4 and folded in host:
                best = max(best, len(folded))
        if best:
            hits.append((best, entry))
    if not hits:
        return None
    best_len = max(length for length, _ in hits)
    return _one_or_none([entry for length, entry in hits if length == best_len])


def expand_see_glossary_body(
    body: str,
    entries: list[dict[str, Any]],
    *,
    host_text: str = "",
) -> str:
    compact = _compact(body)
    if not compact:
        return body
    found = SEE_GLOSSARY.fullmatch(compact)
    if not found:
        return body
    quoted = (found.group("quoted") or "").strip()
    entry = lookup_glossary_entry(quoted, entries) if quoted else infer_glossary_entry(host_text, entries)
    if not entry:
        return body
    return str(entry.get("summary") or "")[:8000]


def glossary_rows_from_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in entries:
        aliases = [alias for alias in entry.get("aliases") or [] if alias and alias != entry.get("name")]
        rows.append(
            glossary_row_from_note(
                {
                    "label": entry.get("name") or "",
                    "aliases": aliases,
                    "body": entry.get("summary") or "",
                    "group_label": KIND_LABEL["glossary"],
                    "kind": "glossary",
                    "marker": "",
                    "anchor": entry.get("name") or "",
                    "chapter": entry.get("chapter") or "",
                }
            )
        )
    return rows


def attach_book_glossary(payload: dict[str, Any], edition: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve See-Glossary footnotes and publish term cards onto a Read payload."""
    chapters = list((edition or {}).get("_chapters") or [])
    if not chapters:
        chapters = list(payload.get("chapters") or [])
    entries = glossary_entries_from_chapters(chapters)
    if not entries:
        return payload
    notes = list(payload.get("notes") or [])
    if notes:
        _expand_notes(notes, entries)
        payload["notes"] = notes
    for chapter in payload.get("chapters") or []:
        _expand_span_notes(chapter.get("blocks") or [], entries)
    _expand_span_notes(payload.get("blocks") or [], entries)
    rows = glossary_rows_from_entries(entries)
    if rows:
        payload["glossary"] = merge_glossary(list(payload.get("glossary") or []), rows)
    return payload


def _parse_entry_chunk(chunk: str, *, chapter: str = "") -> dict[str, Any] | None:
    raw = chunk.strip()
    found = re.match(r"^~([^~\n]+)~", raw)
    if not found:
        return None
    inner = found.group(1).strip()
    period_inside = inner.endswith(".")
    lemma = inner.rstrip(".,;:")
    if not lemma:
        return None
    tail = raw[found.end() :]
    aliases: list[str] = []
    if period_inside or tail.startswith("."):
        name = lemma
    elif re.match(r"^,\s*or\b", tail, re.I):
        name = lemma
        aliases, _ = _or_aliases(tail)
    elif tail.lstrip().startswith(","):
        name = lemma
    elif found_eq := EQUALS_ALIAS.match(tail):
        name = lemma
        alias = found_eq.group(1).strip(" .")
        if alias:
            aliases.append(alias)
    else:
        extra = _title_continuation(tail)
        name = f"{lemma} {extra}".strip() if extra else lemma
    aliases = [alias for alias in aliases if _fold(alias) and _fold(alias) != _fold(name)]
    return {
        "name": name[:300],
        "aliases": aliases,
        "summary": _compact(_strip_marks(raw))[:8000],
        "chapter": chapter,
    }


def _or_aliases(tail: str) -> tuple[list[str], str]:
    aliases: list[str] = []
    rest = tail
    while True:
        found = OR_ALIAS.match(rest)
        if not found:
            break
        alias = found.group(1).strip(" .")
        if alias:
            aliases.append(alias)
        rest = rest[found.end() :]
    return aliases, rest


def _title_continuation(tail: str) -> str:
    found = re.match(r"^[ \t]+([^\n,.]+)", tail)
    if not found:
        return ""
    extra = found.group(1).strip()
    if not extra or extra.split()[0].casefold() == "see" or NOT_TITLE_START.match(extra):
        return ""
    return extra


def _resolve_see_also(entries: list[dict[str, Any]]) -> None:
    originals = [str(entry.get("summary") or "") for entry in entries]
    for entry, original in zip(entries, originals):
        found = SHORT_SEE_ALSO.fullmatch(original)
        if not found:
            continue
        target_name = found.group("target").strip()
        if SEE_PAGE.match(target_name):
            continue
        target = lookup_glossary_entry(target_name, entries, skip=entry)
        if not target:
            continue
        extra = str(target.get("summary") or "").strip()
        if extra and extra != original:
            entry["summary"] = f"{original} {extra}"[:8000]


def _expand_notes(notes: list[dict[str, Any]], entries: list[dict[str, Any]]) -> None:
    for note in notes:
        body = str(note.get("body") or "")
        expanded = expand_see_glossary_body(
            body,
            entries,
            host_text=str(note.get("host_text") or note.get("anchor") or ""),
        )
        if expanded != body:
            note["body"] = expanded[:8000]


def _expand_span_notes(blocks: list[dict[str, Any]], entries: list[dict[str, Any]]) -> None:
    for block in blocks:
        host = str(block.get("text") or "")
        for span in block.get("spans") or []:
            if span.get("style") != "footnote":
                continue
            body = str(span.get("note") or "")
            expanded = expand_see_glossary_body(body, entries, host_text=host)
            if expanded != body:
                span["note"] = expanded[:8000]


def _text_from_blocks(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        text = str(block.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _strip_marks(text: str) -> str:
    return GUTENBERG_STRONG.sub(r"\1", text)


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _fold(text: str) -> str:
    cleaned = _strip_marks(str(text or ""))
    cleaned = cleaned.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    cleaned = re.sub(r"[\"“”«»]", "", cleaned)
    cleaned = re.sub(r"[.]+$", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).casefold().strip()


def _labels(entry: dict[str, Any]) -> list[str]:
    labels = [str(entry.get("name") or "")]
    labels.extend(str(alias) for alias in entry.get("aliases") or [])
    return [label for label in labels if label]


def _unique(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        seen[_fold(str(row.get("name") or ""))] = row
    return list(seen.values())


def _one_or_none(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    unique = _unique(rows)
    return unique[0] if len(unique) == 1 else None


def _disambiguator(summary: str, name: str) -> str:
    rest = _compact(summary)
    folded_name = _fold(name)
    if rest.casefold().startswith(name.casefold()):
        rest = rest[len(name) :].lstrip(" ,.")
    rest = re.sub(r"^(?:or\s+)+", "", rest, flags=re.I)
    words = [word.strip(" ,.") for word in rest.split() if word.strip(" ,.")]
    picked: list[str] = []
    for word in words[:6]:
        if _fold(word) == folded_name:
            continue
        picked.append(word)
        if len(" ".join(picked)) >= 18:
            break
    return " ".join(picked).strip(" ,.")[:60]
