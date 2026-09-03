from __future__ import annotations

import hashlib
import json
import re
from typing import Any

REF_FORMAT = "ref/1"


def reader_visible_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Blocks that belong in reading_markdown / the Read payload."""
    out: list[dict[str, Any]] = []
    for block in blocks:
        if block.get("hidden"):
            continue
        if block.get("type") == "heading" and block.get("suppress_in_reader"):
            continue
        out.append(block)
    return out


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in reader_visible_blocks(blocks):
        kind = block.get("type")
        text = str(block.get("text") or "").strip()
        if kind == "hr":
            parts.append("---")
        elif kind == "heading":
            parts.append(text)
        elif kind == "verse_line":
            parts.append(text)
        elif kind == "stanza":
            parts.append(text)
        elif kind == "blockquote":
            parts.append("> " + text)
        elif kind == "dialogue":
            speaker = block.get("speaker") or ""
            line = text
            parts.append(f"{speaker}. {line}" if speaker else line)
        elif kind == "stage_direction":
            parts.append(f"[{text.strip('[]')}]" if not text.startswith("[") else text)
        elif kind == "list_item":
            parts.append(text)
        elif kind == "metadata":
            parts.append(text)
        elif kind == "paragraph" and text:
            parts.append(text)
    return "\n\n".join(parts).strip()


def split_hints_from_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        if block.get("type") != "heading":
            continue
        level = int(block.get("level") or 1)
        if level > 2:
            continue
        hints.append({"type": "heading", "level": level, "block_index": index, "text": block.get("text") or ""})
    return hints


def detect_content_kind(blocks: list[dict[str, Any]], *, family: str = "plain") -> str:
    kinds = {b.get("type") for b in blocks}
    if family == "scholastic":
        return "scholastic"
    if "dialogue" in kinds or "stage_direction" in kinds:
        return "drama"
    verseish = kinds & {"verse_line", "stanza"}
    if verseish and "paragraph" not in kinds:
        return "verse"
    if verseish:
        return "mixed"
    return "prose"


def edition_hash(
    blocks: list[dict[str, Any]],
    *,
    chapters: list[dict[str, Any]] | None = None,
) -> str:
    """Identity for Read republish. Chapter id/title are included so a remacro
    or new split is a new book even when concatenated REF blocks match."""
    if chapters:
        payload: Any = {
            "blocks": blocks,
            "chapters": [
                {
                    "id": str(ch.get("chapter_id") or ch.get("id") or ""),
                    "title": str(ch.get("title") or ""),
                }
                for ch in chapters
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        raw = json.dumps(blocks, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_edition_document(
    blocks: list[dict[str, Any]],
    *,
    language: str,
    source_family: str,
    quotation_profile: dict[str, Any] | None = None,
    apparatus_dropped: list[str] | None = None,
) -> dict[str, Any]:
    doc = {
        "edition_format": REF_FORMAT,
        "edition_hash": edition_hash(blocks),
        "content_kind": detect_content_kind(blocks, family=source_family),
        "language": language,
        "source_family": source_family,
        "blocks": blocks,
        "reading_markdown": blocks_to_markdown(blocks),
        "split_hints": split_hints_from_blocks(blocks),
    }
    if quotation_profile:
        doc["quotation_profile"] = quotation_profile
    if apparatus_dropped:
        doc["apparatus_dropped"] = apparatus_dropped
    return doc


CHAPTER_ONLY = re.compile(r"^CHAPTER\s+[IVXLC\d]+\.?\s*$", re.I)


def grotius_latin_to_blockquote(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Promote Latin epigraph blocks sandwiched between hr lines to blockquote."""
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if (
            block.get("type") == "hr"
            and i + 1 < len(blocks)
            and blocks[i + 1].get("type") in {"paragraph", "verse_line"}
            and i + 2 < len(blocks)
            and blocks[i + 2].get("type") == "hr"
        ):
            latin = str(blocks[i + 1].get("text") or "")
            if re.search(r"\b(igitur|autem|quod|hinc|gentium|societatem)\b", latin, re.I):
                out.append(block)
                out.append({"type": "blockquote", "text": latin})
                out.append(blocks[i + 2])
                i += 3
                continue
        out.append(block)
        i += 1
    return out
