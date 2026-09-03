"""Stable block ids for Final Touch patches and translation inherit."""

from __future__ import annotations

import re
from typing import Any

_PREFIX_KEEP = re.compile(r"[^a-z0-9]+")


def block_prefix(text: str, *, length: int = 48) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    slug = _PREFIX_KEEP.sub("-", compact).strip("-")
    if not slug:
        return "empty"
    return slug[:length]


def assign_block_ids(blocks: list[dict[str, Any]], *, chapter_id: str = "book") -> list[dict[str, Any]]:
    """Stamp ``block_id`` as ``{chapter}:{type}:{prefix}`` with a numeric suffix on collisions."""
    seen: dict[tuple[str, str], int] = {}
    cid = str(chapter_id or "book").strip() or "book"
    for block in blocks:
        kind = str(block.get("type") or "paragraph")
        prefix = block_prefix(str(block.get("text") or ""))
        key = (kind, prefix)
        n = seen.get(key, 0) + 1
        seen[key] = n
        suffix = "" if n == 1 else f"-{n}"
        block["block_id"] = f"{cid}:{kind}:{prefix}{suffix}"
    return blocks


def match_block_index(
    blocks: list[dict[str, Any]],
    *,
    block_id: str | None = None,
    kind: str | None = None,
    prefix: str | None = None,
    block_index: int | None = None,
) -> int | None:
    """Resolve a patch to an index.

    If ``block_id`` is set it must match exactly. Never fall back to ``block_index``
    in that case — Chế bản always sends both, and a type change after re-parse
    must report stale rather than hide/retarget the row now at that index.
    ``block_index`` is used only when ``block_id`` is omitted.
    """
    if block_id:
        for index, block in enumerate(blocks):
            if block.get("block_id") == block_id:
                return index
        return None
    want_prefix = block_prefix(prefix) if prefix else ""
    if kind and want_prefix:
        hits = [
            i
            for i, block in enumerate(blocks)
            if str(block.get("type") or "") == kind and block_prefix(str(block.get("text") or "")) == want_prefix
        ]
        if len(hits) == 1:
            return hits[0]
    if isinstance(block_index, int) and 0 <= block_index < len(blocks):
        return block_index
    return None


_STRUCT_MARK = re.compile(r"^(?:chapter|chap|book|part|volume)\s+([ivxlcdm]+|\d+)$", re.I)
_STRUCT_KINDS = ("chapter", "chap", "book", "part", "volume")


def heading_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def same_heading(left: str, right: str) -> bool:
    a, b = heading_key(left), heading_key(right)
    return bool(a) and a == b


def _title_has_chapter_number(title_key: str, number: str) -> bool:
    if title_key == number or title_key.startswith(number + " "):
        return True
    for kind in _STRUCT_KINDS:
        token = f"{kind} {number}"
        if title_key == token or title_key.startswith(token + " "):
            return True
    return False


def is_chapter_banner(heading: str, title: str) -> bool:
    """Chrome already prints ``title``; hide a matching CHAPTER/BOOK/PART line.

    Exact match after normalize, or a bare ``CHAPTER III`` whose number is
    the start of a longer TOC title (``III. Early years at Weimar``).
    ``CHAPTER I`` does not match ``CHAPTER II``.
    """
    if same_heading(heading, title):
        return True
    head = heading_key(heading)
    mark = _STRUCT_MARK.match(head)
    if not mark:
        return False
    return _title_has_chapter_number(heading_key(title), mark.group(1))


def _is_banner_candidate(block: dict[str, Any]) -> bool:
    kind = str(block.get("type") or "")
    text = str(block.get("text") or "")
    if kind == "heading":
        return True
    return kind == "paragraph" and bool(_STRUCT_MARK.match(heading_key(text)))


def mark_chapter_banner(blocks: list[dict[str, Any]], title: str | None) -> list[dict[str, Any]]:
    title = str(title or "").strip()
    if not title:
        return blocks
    for block in blocks:
        if not _is_banner_candidate(block):
            continue
        if is_chapter_banner(str(block.get("text") or ""), title):
            block["suppress_in_reader"] = True
            break
    return blocks
