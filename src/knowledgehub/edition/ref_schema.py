"""REF/1 schema constants and validation."""

from __future__ import annotations

from typing import Any

REF_FORMAT = "ref/1"
REF_PARSER_VERSION = "1.8"
DEFAULT_REF_QA_MODEL = "gemini-3.1-flash-lite"

BLOCK_TYPES = frozenset(
    {
        "heading",
        "paragraph",
        "blockquote",
        "verse_line",
        "stanza",
        "hr",
        "list_item",
        "dialogue",
        "stage_direction",
        "metadata",
    }
)
INLINE_STYLES = frozenset(
    {
        "footnote",
        "bracket_note",
        "bracket_cite",
        "bracket_other",
        "paren_cite",
        "paren_quote",
        "paren_aside",
        "paren_page",
        "list_marker",
        "quote",
        "em",
    }
)
CONTENT_KINDS = frozenset({"prose", "verse", "scholastic", "mixed", "drama"})


def validate_block(block: dict[str, Any], *, index: int) -> list[str]:
    errors: list[str] = []
    kind = block.get("type")
    if kind not in BLOCK_TYPES:
        errors.append(f"blocks[{index}].type invalid: {kind!r}")
        return errors
    if kind in {"heading", "paragraph", "blockquote", "verse_line", "dialogue", "list_item", "stage_direction", "metadata", "stanza"}:
        text = block.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"blocks[{index}] missing non-empty text")
    if kind == "dialogue":
        speaker = block.get("speaker")
        if speaker is not None and not isinstance(speaker, str):
            errors.append(f"blocks[{index}].speaker must be string")
    if kind == "heading":
        level = block.get("level")
        if not isinstance(level, int) or not 1 <= level <= 4:
            errors.append(f"blocks[{index}].level must be 1-4")
    for span_index, span in enumerate(block.get("spans") or []):
        if not isinstance(span, dict):
            errors.append(f"blocks[{index}].spans[{span_index}] must be object")
            continue
        style = span.get("style")
        if style not in INLINE_STYLES:
            errors.append(f"blocks[{index}].spans[{span_index}].style invalid: {style!r}")
        for key in ("start", "end"):
            if not isinstance(span.get(key), int):
                errors.append(f"blocks[{index}].spans[{span_index}].{key} must be int")
        text = block.get("text") or ""
        start, end = span.get("start"), span.get("end")
        if isinstance(start, int) and isinstance(end, int) and text:
            if not (0 <= start < end <= len(text)):
                errors.append(f"blocks[{index}].spans[{span_index}] out of range")
            elif span.get("text") and text[start:end] != span.get("text"):
                errors.append(f"blocks[{index}].spans[{span_index}] text mismatch")
    return errors


def validate_edition(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if doc.get("edition_format") != REF_FORMAT:
        errors.append(f"edition_format must be {REF_FORMAT!r}")
    if not isinstance(doc.get("edition_hash"), str) or len(doc.get("edition_hash") or "") != 64:
        errors.append("edition_hash must be sha256 hex")
    kind = doc.get("content_kind")
    if kind not in CONTENT_KINDS:
        errors.append(f"content_kind invalid: {kind!r}")
    blocks = doc.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        errors.append("blocks must be a non-empty list")
        return errors
    md = doc.get("reading_markdown")
    if not isinstance(md, str) or not md.strip():
        errors.append("reading_markdown must be non-empty")
    for index, block in enumerate(blocks):
        if isinstance(block, dict):
            errors.extend(validate_block(block, index=index))
        else:
            errors.append(f"blocks[{index}] must be object")
    return errors
