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
    """Resolve a patch to an index. Prefer exact ``block_id``, then (type, prefix)."""
    if block_id:
        for index, block in enumerate(blocks):
            if block.get("block_id") == block_id:
                return index
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


def same_heading(left: str, right: str) -> bool:
    def norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()

    a, b = norm(left), norm(right)
    return bool(a) and a == b


def mark_chapter_banner(blocks: list[dict[str, Any]], title: str | None) -> list[dict[str, Any]]:
    title = str(title or "").strip()
    if not title:
        return blocks
    for block in blocks:
        if block.get("type") != "heading":
            continue
        if same_heading(str(block.get("text") or ""), title):
            block["suppress_in_reader"] = True
            break
    return blocks
