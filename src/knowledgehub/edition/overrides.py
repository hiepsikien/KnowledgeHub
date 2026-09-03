"""Apply curator overrides to REF/1 block arrays."""

from __future__ import annotations

import copy
from typing import Any

from .block_ids import assign_block_ids, block_prefix, match_block_index
from .inline_spans import annotate_blocks
from .serialize import build_edition_document

STRUCTURAL_ACTIONS = frozenset({"merge_with_next", "merge", "split"})


def _merge_block_with_next(blocks: list[dict[str, Any]], index: int) -> None:
    if index < 0 or index >= len(blocks) - 1:
        return
    left = blocks[index]
    right = blocks[index + 1]
    if left.get("type") not in {"paragraph", "blockquote", "dialogue", "metadata", "list_item"}:
        return
    if right.get("type") not in {"paragraph", "blockquote", "dialogue", "metadata", "list_item"}:
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


def _split_block(blocks: list[dict[str, Any]], index: int, at: int) -> None:
    if index < 0 or index >= len(blocks):
        return
    block = blocks[index]
    text = str(block.get("text") or "")
    if at <= 0 or at >= len(text):
        return
    left_text = text[:at].rstrip()
    right_text = text[at:].lstrip()
    if not left_text or not right_text:
        return
    left = dict(block)
    left["text"] = left_text
    left.pop("spans", None)
    right = dict(block)
    right["text"] = right_text
    right.pop("spans", None)
    right.pop("block_id", None)
    blocks[index] = left
    blocks.insert(index + 1, right)


def _resolve_index(blocks: list[dict[str, Any]], patch: dict[str, Any]) -> int | None:
    return match_block_index(
        blocks,
        block_id=str(patch.get("block_id") or "") or None,
        kind=str(patch.get("type") or patch.get("match_type") or "") or None,
        prefix=str(patch.get("prefix") or "") or None,
        block_index=patch.get("block_index") if isinstance(patch.get("block_index"), int) else None,
    )


def apply_block_patches(
    blocks: list[dict[str, Any]],
    patches: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply Final Touch patches by ``block_id`` (index is fallback). Returns (blocks, stale)."""
    out = copy.deepcopy(blocks)
    stale: list[dict[str, Any]] = []
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        action = str(patch.get("action") or "").strip()
        index = _resolve_index(out, patch)
        if index is None:
            stale.append({**dict(patch), "stale": True, "reason": "block_id not found after re-parse"})
            continue
        if action in {"merge_with_next", "merge"}:
            _merge_block_with_next(out, index)
            continue
        if action == "split":
            at = patch.get("at")
            if not isinstance(at, int):
                stale.append({**dict(patch), "stale": True, "reason": "split requires integer at"})
                continue
            _split_block(out, index, at)
            continue
        block = out[index]
        if action == "hide":
            block["hidden"] = True
            continue
        if action == "show":
            block["hidden"] = False
            continue
        if "hidden" in patch and patch["hidden"] is not None:
            block["hidden"] = bool(patch["hidden"])
        if action == "set_type" or ("type" in patch and patch["type"] and action != "split"):
            if patch.get("type"):
                block["type"] = patch["type"]
        if action == "set_text":
            if "text" in patch and patch["text"] is not None:
                block["text"] = str(patch["text"])
                block.pop("spans", None)
                block["lexical"] = True
        elif "text" in patch and patch["text"] is not None and action not in STRUCTURAL_ACTIONS | {"hide", "show"}:
            new_text = str(patch["text"])
            if new_text != str(block.get("text") or ""):
                block["text"] = new_text
                block.pop("spans", None)
                if patch.get("lexical"):
                    block["lexical"] = True
        if block.get("type") == "heading" and "level" in patch and patch["level"] is not None:
            block["level"] = int(patch["level"])
        if block.get("type") == "dialogue" and "speaker" in patch:
            block["speaker"] = patch["speaker"]
        if "role" in patch and patch["role"] is not None:
            block["role"] = patch["role"]
    chapter_id = "book"
    if out and isinstance(out[0].get("block_id"), str) and ":" in str(out[0]["block_id"]):
        chapter_id = str(out[0]["block_id"]).split(":", 1)[0]
    assign_block_ids(out, chapter_id=chapter_id)
    annotated, _profile = annotate_blocks(out)
    return annotated, stale


def _coalesce_key(patch: dict[str, Any]) -> str | None:
    action = str(patch.get("action") or "")
    if action in STRUCTURAL_ACTIONS:
        return None
    if patch.get("block_id"):
        return f"id:{patch['block_id']}"
    index = patch.get("block_index")
    if isinstance(index, int):
        return f"idx:{index}"
    kind = str(patch.get("match_type") or patch.get("type") or "")
    prefix = str(patch.get("prefix") or "")
    if kind and prefix:
        return f"pfx:{kind}:{block_prefix(prefix)}"
    return None


def merge_block_patches(
    existing: list[dict[str, Any]] | None,
    incoming: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Accumulate curator patches across saves.

    Field edits for the same ``block_id`` (else ``block_index``) coalesce (last wins).
    ``merge_with_next`` / ``split`` append in order and are not collapsed.
    """
    combined = list(existing or []) + list(incoming or [])
    result: list[dict[str, Any]] = []
    last_pos: dict[str, int] = {}
    for patch in combined:
        if not isinstance(patch, dict):
            continue
        key = _coalesce_key(patch)
        if key is None:
            result.append(dict(patch))
            continue
        if key in last_pos:
            prev = result[last_pos[key]]
            merged = dict(prev)
            for field, value in patch.items():
                if value is not None:
                    merged[field] = value
            incoming_action = str(patch.get("action") or "")
            if incoming_action == "hide":
                merged["hidden"] = True
            elif incoming_action == "show":
                merged["hidden"] = False
            result[last_pos[key]] = merged
        else:
            last_pos[key] = len(result)
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
        patched, _stale = apply_block_patches(slice_blocks, patches)
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
