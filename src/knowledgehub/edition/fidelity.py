"""Deterministic fidelity checks — no LLM cost."""

from __future__ import annotations

import re
from typing import Any

from .ref_schema import validate_edition
from .serialize import blocks_to_markdown


def compact_text(text: str) -> str:
    """Remove whitespace for order-preserving subsequence checks."""
    return re.sub(r"\s+", "", text or "")


def edition_text_from_blocks(edition: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in edition.get("blocks") or []:
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "\n\n".join(parts)


def is_subsequence(haystack: str, needle: str) -> bool:
    if not needle:
        return True
    index = 0
    for ch in haystack:
        if ch == needle[index]:
            index += 1
            if index >= len(needle):
                return True
    return False


def check_text_subsequence(source: str, edition: dict[str, Any]) -> dict[str, Any]:
    """Edition prose must appear in source order with no rewritten tokens."""
    body = edition_text_from_blocks(edition)
    src = compact_text(source)
    out = compact_text(body)
    ok = is_subsequence(src, out)
    return {
        "id": "text_subsequence",
        "passed": ok,
        "severity": "critical" if not ok else "none",
        "source_chars": len(src),
        "edition_chars": len(out),
        "note_vi": (
            "Văn bản block khớp thứ tự ký tự với nguồn (chỉ bỏ khoảng trắng)."
            if ok
            else "Văn bản REF lệch nguồn — có thể bị sửa từ, thiếu đoạn, hoặc join sai."
        ),
    }


def check_markdown_consistency(edition: dict[str, Any]) -> dict[str, Any]:
    blocks = edition.get("blocks") or []
    expected = blocks_to_markdown(blocks)
    actual = str(edition.get("reading_markdown") or "")
    ok = expected == actual
    return {
        "id": "markdown_consistency",
        "passed": ok,
        "severity": "major" if not ok else "none",
        "note_vi": "reading_markdown khớp blocks." if ok else "reading_markdown lệch blocks_to_markdown().",
    }


def check_schema(edition: dict[str, Any]) -> dict[str, Any]:
    errors = validate_edition(edition)
    return {
        "id": "schema",
        "passed": not errors,
        "severity": "critical" if errors else "none",
        "errors": errors,
        "note_vi": "REF/1 schema hợp lệ." if not errors else f"{len(errors)} lỗi schema.",
    }


def check_span_offsets(edition: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    for block_index, block in enumerate(edition.get("blocks") or []):
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "")
        for span_index, span in enumerate(block.get("spans") or []):
            if not isinstance(span, dict):
                issues.append(f"blocks[{block_index}].spans[{span_index}] not object")
                continue
            start, end = span.get("start"), span.get("end")
            if not isinstance(start, int) or not isinstance(end, int):
                issues.append(f"blocks[{block_index}].spans[{span_index}] bad offsets")
                continue
            if not (0 <= start < end <= len(text)):
                issues.append(f"blocks[{block_index}].spans[{span_index}] out of range")
            elif span.get("text") and text[start:end] != span.get("text"):
                issues.append(f"blocks[{block_index}].spans[{span_index}] text mismatch")
    return {
        "id": "span_offsets",
        "passed": not issues,
        "severity": "major" if issues else "none",
        "errors": issues,
        "note_vi": "Inline span offsets khớp text." if not issues else f"{len(issues)} lỗi span.",
    }


def check_block_sanity(edition: dict[str, Any], *, max_blocks: int = 500) -> dict[str, Any]:
    blocks = edition.get("blocks") or []
    issues: list[str] = []
    if len(blocks) > max_blocks:
        issues.append(f"block_count={len(blocks)} > {max_blocks}")
    empty_paragraphs = sum(
        1
        for b in blocks
        if b.get("type") in {"paragraph", "heading", "verse_line", "blockquote"}
        and not str(b.get("text") or "").strip()
    )
    if empty_paragraphs:
        issues.append(f"{empty_paragraphs} empty textual blocks")
    return {
        "id": "block_sanity",
        "passed": not issues,
        "severity": "minor" if issues else "none",
        "errors": issues,
        "note_vi": "Cấu trúc block hợp lý." if not issues else "; ".join(issues),
    }


def run_fidelity_checks(source: str, edition: dict[str, Any]) -> dict[str, Any]:
    checks = [
        check_schema(edition),
        check_text_subsequence(source, edition),
        check_markdown_consistency(edition),
        check_span_offsets(edition),
        check_block_sanity(edition),
    ]
    failed = [c for c in checks if not c["passed"]]
    return {
        "passed": not failed,
        "checks": checks,
        "failed_count": len(failed),
        "critical_count": sum(1 for c in failed if c.get("severity") == "critical"),
    }
