"""Parse a Glossary chapter and resolve See Glossary pointers at publish.

Printed books park term definitions in back matter. Hub inlines those bodies
onto footnote markers and publishes ``glossary[]`` cards so Read can show them
without a new UI. The Glossary chapter itself stays in the chapter list.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .footnotes import KIND_LABEL, attach_note_hosts, glossary_row_from_note, merge_glossary

HEADWORD = re.compile(r"^~([^~]{1,80})~")
POINTER = re.compile(
    r"^(?:see\s+glossary|xem\s+bảng\s+chú\s+giải)\s*"
    r"(?:[,:]\s*)?"
    r'(?:[“"«(\[]*(.+?)[”"»)\].]*)?'
    r"\s*\.?$",
    re.I | re.S,
)
SEE_ENTRY = re.compile(
    r"^\s*see\s+(?!glossary\b|p\.|page\b)(.+?)\s*\.?$",
    re.I,
)
NAME_PARTICLE = re.compile(
    r"^\s+((?:(?:da|de|di|von|of)\s+|d['’])[A-Za-zÀ-ỹ'’-]+"
    r"(?:\s+(?:(?:da|de|di|von|of)\s+|d['’])?[A-Za-zÀ-ỹ'’-]+)*)",
    re.I,
)
NAME_TRAIL = re.compile(r"^\s+(piccolo|pomposa)\b", re.I)
NAME_TITLE = re.compile(r"^\s+([A-ZÀ-Ỵ][\wÀ-ỹ'’-]*)([.,])")
OR_STOP = re.compile(r"\s+for\b|\s+was\b|\s+which\b", re.I)
OTHER_NAMES = re.compile(r"Other names were\s+(.+?)(?:\.|$)", re.I)
ENGLISH_ALIAS = re.compile(r'\((?:English\s+)?[“"]([^”"]+)[”"]\)', re.I)
GIVEN_NAME = re.compile(
    r"^(?:Joh\.?|Johann|J\.|G\.|Georg|Christian|Andreas|Dietrich|"
    r"Antonius|Heinrich|Reinhard|Samuel|Philipp|Friedrich)\b",
    re.I,
)
GLOSSARY_TITLE = re.compile(r"^(glossary|bảng chú giải)\b", re.I)
TILDEN = re.compile(r"~([^~]+)~")
NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass
class GlossaryEntry:
    name: str
    body: str
    aliases: list[str] = field(default_factory=list)
    redirect: str = ""

    def keys(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in [self.name, *self.aliases]:
            key = fold_key(raw)
            if len(key) < 3 or key in seen:
                continue
            seen.add(key)
            out.append(raw)
        return out


def fold_key(text: str) -> str:
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(ch)
    )
    return NON_ALNUM.sub("", stripped.casefold())


def strip_tildes(text: str) -> str:
    return TILDEN.sub(r"\1", text)


def compact_body(text: str) -> str:
    return re.sub(r"\s+", " ", strip_tildes(text)).strip()


def is_glossary_chapter(chapter: dict[str, Any]) -> bool:
    title = str(chapter.get("title") or chapter.get("ref_title") or "").strip()
    if GLOSSARY_TITLE.match(title):
        return True
    for block in chapter.get("blocks") or []:
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        return bool(re.fullmatch(r"(glossary|bảng chú giải)\.?", text, re.I))
    return False


def parse_glossary_pointer(text: str) -> tuple[bool, str]:
    """Return (is_pointer, cited_term). cited_term is empty for a bare See Glossary."""
    blob = compact_body(re.sub(r"^\[\d+\]\s*", "", str(text or "").strip()))
    if not blob:
        return False, ""
    match = POINTER.fullmatch(blob)
    if not match:
        return False, ""
    cited = compact_body(match.group(1) or "").strip(" .,;:")
    return True, cited


def _expand_name(head: str, rest: str) -> str:
    particle = NAME_PARTICLE.match(rest)
    if particle:
        extra = particle.group(1).strip(" .,")
        return f"{head} {extra}".strip()
    trail = NAME_TRAIL.match(rest)
    if trail:
        return f"{head} {trail.group(1)}".strip()
    title = NAME_TITLE.match(rest)
    if title:
        return f"{head} {title.group(1)}".strip()
    return head


def _or_aliases(rest: str) -> list[str]:
    blob = rest.lstrip(" ,")
    if not re.match(r"^or\s+", blob, re.I):
        return []
    stop = OR_STOP.search(blob)
    chunk = blob[: stop.start()] if stop else blob
    parts = re.split(r",\s*or\s+", re.sub(r"^or\s+", "", chunk, count=1, flags=re.I), flags=re.I)
    out: list[str] = []
    for part in parts:
        token = compact_body(part).strip(" .,")
        if 1 < len(token) < 80:
            out.append(token)
    return out


def _equals_alias(rest: str) -> list[str]:
    match = re.match(r"^\s*=\s*([^,]+)", rest)
    if not match:
        return []
    token = compact_body(match.group(1)).strip(" .,")
    return [token] if 1 < len(token) < 80 else []


def _comma_aliases(rest: str) -> list[str]:
    if not rest.startswith(","):
        return []
    chunk = rest[1:].lstrip()
    if chunk.lower().startswith(("or ", "=", "see ")):
        return []
    out: list[str] = []
    while chunk:
        match = re.match(
            r"^([A-ZÀ-Ỵ][\wÀ-ỹ'’.\-]*(?:\s+[A-ZÀ-Ỵ][\wÀ-ỹ'’.\-]*){0,3})\s*([,.]|$)\s*",
            chunk,
        )
        if not match:
            break
        token = match.group(1).strip().rstrip(".")
        if GIVEN_NAME.match(token) or re.search(r"\d", token):
            break
        if 1 < len(token) < 80:
            out.append(token)
        if match.group(2) != ",":
            break
        chunk = chunk[match.end() :]
        if chunk and chunk[0].islower():
            break
    return out


def _aliases_from_rest(rest: str, body: str) -> list[str]:
    aliases = _or_aliases(rest) + _equals_alias(rest) + _comma_aliases(rest)
    for match in ENGLISH_ALIAS.finditer(body):
        token = compact_body(match.group(1)).strip(" .,")
        if 1 < len(token) < 80:
            aliases.append(token)
    other = OTHER_NAMES.search(body)
    if other:
        for part in re.split(r",| and ", other.group(1)):
            token = compact_body(part).strip(" .,")
            if 1 < len(token) < 40:
                aliases.append(token)
    seen: set[str] = set()
    out: list[str] = []
    for alias in aliases:
        key = fold_key(alias)
        if key in seen:
            continue
        seen.add(key)
        out.append(alias)
    return out


def parse_glossary_blocks(blocks: list[dict[str, Any]]) -> list[GlossaryEntry]:
    entries: list[GlossaryEntry] = []
    current: GlossaryEntry | None = None
    for block in blocks:
        if block.get("hidden") or block.get("suppress_in_reader"):
            continue
        text = str(block.get("text") or "").strip()
        if not text or re.fullmatch(r"(glossary|bảng chú giải)\.?", text, re.I):
            continue
        match = HEADWORD.match(text)
        if match:
            if current:
                entries.append(current)
            head = match.group(1).strip(" .")
            rest = text[match.end() :]
            name = _expand_name(head, rest)
            redirect = ""
            see = SEE_ENTRY.match(rest.lstrip(" ."))
            if see:
                redirect = compact_body(see.group(1)).strip(" .,")
            body = compact_body(text)
            current = GlossaryEntry(
                name=name,
                body=body,
                aliases=_aliases_from_rest(rest, body),
                redirect=redirect,
            )
            if fold_key(head) != fold_key(name) and len(fold_key(head)) >= 8:
                current.aliases = [head, *current.aliases]
            continue
        if current:
            extra = compact_body(text)
            if extra:
                current.body = f"{current.body} {extra}".strip()
                known = {fold_key(alias) for alias in current.aliases}
                for alias in _aliases_from_rest("", extra):
                    if fold_key(alias) not in known:
                        current.aliases.append(alias)
                        known.add(fold_key(alias))
    if current:
        entries.append(current)
    return _fold_redirects(entries)


def _fold_redirects(entries: list[GlossaryEntry]) -> list[GlossaryEntry]:
    by_key: dict[str, GlossaryEntry] = {}
    for entry in entries:
        if entry.redirect:
            continue
        key = fold_key(entry.name)
        existing = by_key.get(key)
        if existing:
            existing.body = f"{existing.body}\n\n{entry.body}".strip()
            for alias in entry.aliases:
                if fold_key(alias) not in {fold_key(a) for a in existing.aliases}:
                    existing.aliases.append(alias)
            continue
        by_key[key] = GlossaryEntry(
            name=entry.name,
            body=entry.body,
            aliases=list(entry.aliases),
        )
    for entry in entries:
        if not entry.redirect:
            continue
        target = lookup_entry(entry.redirect, list(by_key.values()))
        if target is None:
            by_key.setdefault(
                fold_key(entry.name),
                GlossaryEntry(name=entry.name, body=entry.body, aliases=list(entry.aliases)),
            )
            continue
        for alias in [entry.name, *entry.aliases]:
            if fold_key(alias) not in {fold_key(a) for a in [target.name, *target.aliases]}:
                target.aliases.append(alias)
    return list(by_key.values())


def lookup_entry(query: str, entries: list[GlossaryEntry]) -> GlossaryEntry | None:
    needle = fold_key(query)
    if len(needle) < 3:
        return None
    exact: list[GlossaryEntry] = []
    prefix: list[GlossaryEntry] = []
    for entry in entries:
        keys = [fold_key(item) for item in entry.keys()]
        if needle in keys:
            exact.append(entry)
            continue
        if any(key.startswith(needle) or needle.startswith(key) for key in keys if len(key) >= 4):
            prefix.append(entry)
    if len(exact) == 1:
        return exact[0]
    if exact:
        exact.sort(key=lambda row: len(fold_key(row.name)))
        return exact[0]
    if len(prefix) == 1:
        return prefix[0]
    if prefix:
        prefix.sort(key=lambda row: abs(len(fold_key(row.name)) - len(needle)))
        return prefix[0]
    return None


def _term_hits(text: str, entries: list[GlossaryEntry]) -> list[GlossaryEntry]:
    """Longest-first unique entries whose name/alias appears as a whole token."""
    compact_src: list[str] = []
    index_map: list[int] = []
    for index, char in enumerate(text):
        folded = char.casefold()
        stripped = "".join(
            ch for ch in unicodedata.normalize("NFKD", folded) if not unicodedata.combining(ch)
        )
        if stripped.isalnum():
            compact_src.append(stripped)
            index_map.append(index)
    haystack = "".join(compact_src)
    ranked = sorted(entries, key=lambda row: max((len(fold_key(k)) for k in row.keys()), default=0), reverse=True)
    hits: list[GlossaryEntry] = []
    occupied = [False] * len(haystack)
    for entry in ranked:
        keys = sorted((fold_key(k) for k in entry.keys()), key=len, reverse=True)
        for key in keys:
            if len(key) < 3:
                continue
            start = 0
            while True:
                found = haystack.find(key, start)
                if found < 0:
                    break
                end = found + len(key)
                orig_start = index_map[found]
                orig_end = index_map[end - 1] + 1
                before = text[orig_start - 1] if orig_start else " "
                after = text[orig_end] if orig_end < len(text) else " "
                if before.isalnum() or after.isalnum() or any(occupied[found:end]):
                    start = found + 1
                    continue
                hits.append(entry)
                for pos in range(found, end):
                    occupied[pos] = True
                break
            else:
                continue
            break
    return hits


def _nearest_hit(text: str, at: int, entries: list[GlossaryEntry]) -> GlossaryEntry | None:
    window = text[max(0, at - 96) : at]
    hits = _term_hits(window, entries)
    return hits[-1] if hits else None


def resolve_pointer_body(
    body: str,
    entries: list[GlossaryEntry],
    *,
    host_text: str = "",
    marker_at: int | None = None,
) -> str | None:
    is_pointer, cited = parse_glossary_pointer(body)
    if not is_pointer:
        return None
    if cited:
        hit = lookup_entry(cited, entries)
        return hit.body if hit else None
    if marker_at is not None and host_text:
        near = _nearest_hit(host_text, marker_at, entries)
        if near:
            return near.body
    hits = _term_hits(host_text, entries) if host_text else []
    if not hits:
        return None
    unique: list[GlossaryEntry] = []
    seen: set[str] = set()
    for hit in hits:
        key = fold_key(hit.name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    if len(unique) == 1:
        return unique[0].body
    return "\n\n".join(item.body for item in unique)


def glossary_cards(entries: list[GlossaryEntry], *, chapter: str = "") -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for entry in entries:
        cards.append(
            glossary_row_from_note(
                {
                    "kind": "glossary",
                    "label": entry.name[:300],
                    "anchor": entry.name[:300],
                    "body": entry.body[:8000],
                    "group_label": KIND_LABEL["glossary"],
                    "aliases": entry.aliases[:24],
                    "chapter": chapter,
                    "marker": "",
                }
            )
        )
    return cards


def parse_glossary_from_edition(edition: dict[str, Any]) -> list[GlossaryEntry]:
    for chapter in edition.get("_chapters") or []:
        if is_glossary_chapter(chapter):
            return parse_glossary_blocks(list(chapter.get("blocks") or []))
    return []


def _resolve_block_spans(block: dict[str, Any], entries: list[GlossaryEntry]) -> None:
    text = str(block.get("text") or "")
    spans = block.get("spans") or []
    for span in spans:
        if span.get("style") != "footnote":
            continue
        note = str(span.get("note") or "")
        if not parse_glossary_pointer(note)[0]:
            continue
        start = span.get("start")
        at = start if isinstance(start, int) else text.find(str(span.get("text") or ""))
        resolved = resolve_pointer_body(note, entries, host_text=text, marker_at=at if at >= 0 else None)
        if resolved:
            span["note"] = resolved[:8000]


def _resolve_note_row(note: dict[str, Any], entries: list[GlossaryEntry]) -> None:
    body = str(note.get("body") or note.get("summary") or "")
    host = str(note.get("host_text") or "")
    resolved = resolve_pointer_body(body, entries, host_text=host)
    if resolved:
        if "body" in note or "summary" not in note:
            note["body"] = resolved[:8000]
        if "summary" in note:
            note["summary"] = resolved[:8000]


def resolve_glossary_in_edition(edition: dict[str, Any]) -> list[GlossaryEntry]:
    """Replace See Glossary pointers on the in-memory edition (before publish hash)."""
    entries = parse_glossary_from_edition(edition)
    if not entries:
        return []
    for chapter in edition.get("_chapters") or []:
        for block in chapter.get("blocks") or []:
            _resolve_block_spans(block, entries)
        for note in chapter.get("notes") or []:
            _resolve_note_row(note, entries)
    for block in edition.get("blocks") or []:
        _resolve_block_spans(block, entries)
    for note in edition.get("notes") or []:
        _resolve_note_row(note, entries)
    return entries


def attach_published_glossary(payload: dict[str, Any], edition: dict[str, Any]) -> list[GlossaryEntry]:
    """Resolve remaining pointers on the Read payload and merge term cards.

    Does not hide the Glossary chapter or add inline glossary spans.
    """
    entries = parse_glossary_from_edition(edition)
    if entries:
        host_blocks: list[dict[str, Any]] = list(payload.get("blocks") or [])
        for chapter in payload.get("chapters") or []:
            host_blocks.extend(chapter.get("blocks") or [])
        attach_note_hosts(list(payload.get("notes") or []), host_blocks)
        for block in payload.get("blocks") or []:
            _resolve_block_spans(block, entries)
        for chapter in payload.get("chapters") or []:
            for block in chapter.get("blocks") or []:
                _resolve_block_spans(block, entries)
        for note in payload.get("notes") or []:
            _resolve_note_row(note, entries)
        chapter_id = ""
        for chapter in edition.get("_chapters") or []:
            if is_glossary_chapter(chapter):
                chapter_id = str(chapter.get("chapter_id") or chapter.get("id") or "")
                break
        cards = glossary_cards(entries, chapter=chapter_id)
        payload["glossary"] = merge_glossary(list(payload.get("glossary") or []), cards)
    return entries
