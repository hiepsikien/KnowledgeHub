"""Apply curator overrides to REF/1 block arrays."""

from __future__ import annotations

import copy
from typing import Any

from .serialize import blocks_to_markdown, build_edition_document, edition_hash


def _merge_block_with_next(blocks: list[dict[str, Any]], index: int) -> None:
    if index < 0 or index >= len(blocks) - 1:
        return
    left = blocks[index]
    right = blocks[index + 1]
    if left.get("type") not in {"paragraph", "blockquote", "dialogue", "metadata"}:
        return
    if right.get("type") not in {"paragraph", "blockquote", "dialogue", "metadata"}:
        return
    left_text = str(left.get("text") or "").rstrip()
    right_text = str(right.get("text") or "").lstrip()
    joiner = " " if left_text and right_text and not left_text.endswith("-") else ""
    if left_text.endswith("-"):
        left_text = left_text[:-1]
        joiner = ""
    merged = left_text + joiner + right_text
    left["text"] = merged
    left.pop("spans", None)
    blocks.pop(index + 1)


def apply_block_patches(blocks: list[dict[str, Any]], patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = copy.deepcopy(blocks)
    for patch in patches:
        action = patch.get("action")
        index = patch.get("block_index")
        if action == "merge_with_next":
            if isinstance(index, int):
                _merge_block_with_next(out, index)
            continue
        if not isinstance(index, int) or index < 0 or index >= len(out):
            continue
        block = out[index]
        if "type" in patch and patch["type"]:
            block["type"] = patch["type"]
        if "text" in patch and patch["text"] is not None:
            block["text"] = str(patch["text"])
            block.pop("spans", None)
        if block.get("type") == "heading" and "level" in patch:
            block["level"] = int(patch["level"])
        if block.get("type") == "dialogue" and "speaker" in patch:
            block["speaker"] = patch["speaker"]
    return out


def merge_block_patches(
    existing: list[dict[str, Any]] | None,
    incoming: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Accumulate curator patches across saves.

    Field edits for the same ``block_index`` coalesce (last wins).
    ``merge_with_next`` actions append in order and are not collapsed.
    """
    combined = list(existing or []) + list(incoming or [])
    result: list[dict[str, Any]] = []
    last_pos: dict[int, int] = {}
    for patch in combined:
        if not isinstance(patch, dict):
            continue
        if patch.get("action") == "merge_with_next":
            result.append(dict(patch))
            continue
        index = patch.get("block_index")
        if not isinstance(index, int):
            result.append(dict(patch))
            continue
        if index in last_pos:
            prev = result[last_pos[index]]
            merged = dict(prev)
            for key, value in patch.items():
                if value is not None:
                    merged[key] = value
            result[last_pos[index]] = merged
        else:
            last_pos[index] = len(result)
            result.append(dict(patch))
    return result


def apply_chapter_overrides(
    edition: dict[str, Any],
    overrides: dict[str, Any],
    *,
    chapter_specs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a new edition document with curator patches applied."""
    blocks = copy.deepcopy(edition.get("blocks") or [])
    for spec in chapter_specs:
        ch_id = spec["chapter_id"]
        ch_override = overrides.get(ch_id) or {}
        patches = ch_override.get("block_patches") or []
        if not patches:
            continue
        start = int(spec["block_start"])
        end = int(spec["block_end"])
        slice_blocks = blocks[start : end + 1]
        patched = apply_block_patches(slice_blocks, patches)
        blocks[start : end + 1] = patched
        delta = len(patched) - len(slice_blocks)
        if delta:
            for other in chapter_specs:
                if int(other["block_start"]) > end:
                    other["block_start"] = int(other["block_start"]) + delta
                    other["block_end"] = int(other["block_end"]) + delta
            end += delta
        spec["block_end"] = end
    language = str(edition.get("language") or "en")
    source_family = str(edition.get("source_family") or "plain")
    return build_edition_document(
        blocks,
        language=language,
        source_family=source_family,
        quotation_profile=edition.get("quotation_profile"),
        apparatus_dropped=edition.get("apparatus_dropped"),
    )


def overrides_digest(overrides: dict[str, Any]) -> str:
    import json

    payload = json.dumps(overrides, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
