from __future__ import annotations

from .label_rules import LineLabel
from .lines import TextLine


def _glue(prev: str, nxt: str) -> str:
    if prev.rstrip().endswith("-") and nxt[:1].islower():
        return prev.rstrip()[:-1] + nxt
    return prev.rstrip() + " " + nxt.lstrip()


def labels_to_blocks(lines: list[TextLine], labels: list[LineLabel]) -> list[dict]:
    if len(lines) != len(labels):
        raise ValueError("lines and labels length mismatch")
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        label = labels[i]
        text = lines[i].text
        if label.role == "hr":
            blocks.append({"type": "hr"})
            i += 1
            continue
        if label.role in {"heading", "verse_line"}:
            block: dict = {"type": label.role if label.role != "verse_line" else "verse_line", "text": text}
            if label.role == "heading":
                block["level"] = label.level or 1
            blocks.append(block)
            i += 1
            continue
        if label.role == "blockquote":
            parts = [text]
            i += 1
            while i < len(lines) and labels[i].role == "blockquote":
                parts.append(lines[i].text)
                i += 1
            blocks.append({"type": "blockquote", "text": " ".join(parts)})
            continue
        parts = [text]
        i += 1
        while i > 0 and labels[i - 1].join_next and i < len(lines):
            parts.append(lines[i].text)
            i += 1
        merged = parts[0]
        for part in parts[1:]:
            merged = _glue(merged, part)
        blocks.append({"type": "paragraph", "text": merged})
    return blocks
