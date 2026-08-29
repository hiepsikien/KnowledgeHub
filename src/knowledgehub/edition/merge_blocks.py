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
        if label.role == "metadata":
            blocks.append({"type": "metadata", "text": text})
            i += 1
            continue
        if label.role == "stage_direction":
            blocks.append({"type": "stage_direction", "text": text})
            i += 1
            continue
        if label.role == "list_item":
            blocks.append({"type": "list_item", "text": text})
            i += 1
            continue
        if label.role == "speaker_cue":
            speaker = text.strip().rstrip(".")
            i += 1
            parts: list[str] = []
            while i < len(lines) and labels[i].role == "dialogue_line":
                parts.append(lines[i].text)
                if not labels[i].join_next:
                    i += 1
                    break
                i += 1
            if parts:
                merged = parts[0]
                for part in parts[1:]:
                    merged = _glue(merged, part)
                blocks.append({"type": "dialogue", "speaker": speaker, "text": merged})
            continue
        if label.role == "verse_line":
            parts = [text]
            stanza_start = lines[i].blank_before
            i += 1
            while i < len(lines) and labels[i - 1].join_next:
                parts.append(lines[i].text)
                i += 1
            merged = parts[0]
            for part in parts[1:]:
                merged = _glue(merged, part)
            stripped = merged.strip()
            kind = (
                "blockquote"
                if stripped.startswith(('"', "“", "«", "_"))
                or (len(parts) > 1 and ('"' in merged or "“" in merged))
                else "verse_line"
            )
            block: dict = {"type": kind, "text": merged}
            if kind == "verse_line":
                block["stanza_start"] = stanza_start
            blocks.append(block)
            continue
        if label.role == "heading":
            blocks.append({"type": "heading", "text": text, "level": label.level or 1})
            i += 1
            continue
        if label.role == "dialogue_line":
            parts = [text]
            i += 1
            while i < len(lines) and labels[i].role == "dialogue_line" and labels[i - 1].join_next:
                parts.append(lines[i].text)
                i += 1
            merged = parts[0]
            for part in parts[1:]:
                merged = _glue(merged, part)
            blocks.append({"type": "paragraph", "text": merged})
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
