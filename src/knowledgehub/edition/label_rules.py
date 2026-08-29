from __future__ import annotations

import re
from dataclasses import dataclass

from .lines import TextLine
from .reflow import ORDINAL_WRAP, is_all_caps_heading, is_hard_structural, is_soft_structural

RULE_LINE = re.compile(r"^[\-–—_\*=\s]{8,}$")
ITALIC_LINE = re.compile(r"^_([^_].*[^_])_$")
SENTENCE_END = re.compile(r"""[.!?]["'\])]*$""")
CONTINUATION_START = re.compile(r"^[a-z(\[]")
HYPHEN_BREAK = re.compile(r"-$")


@dataclass
class LineLabel:
    index: int
    role: str
    level: int = 0
    join_next: bool = False
    confidence: float = 1.0
    source: str = "rule"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "role": self.role,
            "level": self.level,
            "join_next": self.join_next,
            "confidence": self.confidence,
            "source": self.source,
        }


def _role_for_line(line: str, *, family: str) -> tuple[str, int, float]:
    if RULE_LINE.match(line):
        return "hr", 0, 0.98
    if is_hard_structural(line, family=family):
        level = 1 if re.match(r"^(?:CHAPTER|BOOK|PART|VOLUME)\b", line, re.I) else 2
        return "heading", level, 0.95
    if is_soft_structural(line, family=family):
        return "heading", 3, 0.9
    if ITALIC_LINE.match(line):
        return "heading", 2, 0.88
    if is_all_caps_heading(line):
        return "heading", 2, 0.82
    return "prose", 0, 0.92


def _should_join(prev: str, nxt: str, *, family: str) -> bool:
    if is_hard_structural(nxt, family=family) or is_soft_structural(nxt, family=family):
        return False
    if RULE_LINE.match(nxt):
        return False
    if HYPHEN_BREAK.search(prev.rstrip()) and nxt[:1].islower():
        return True
    if CONTINUATION_START.match(nxt) and not SENTENCE_END.search(prev.rstrip()):
        return True
    if len(prev) >= ORDINAL_WRAP and not SENTENCE_END.search(prev.rstrip()):
        return True
    if prev.rstrip().endswith((",", ";", ":")) and CONTINUATION_START.match(nxt):
        return True
    return False


def label_lines_rules(lines: list[TextLine], *, family: str = "gutenberg") -> list[LineLabel]:
    labels: list[LineLabel] = []
    for row in lines:
        role, level, confidence = _role_for_line(row.text, family=family)
        labels.append(
            LineLabel(index=row.index, role=role, level=level, confidence=confidence)
        )
    for i, label in enumerate(labels):
        if label.role != "prose":
            continue
        if i + 1 >= len(labels):
            continue
        nxt = labels[i + 1]
        if nxt.role != "prose":
            continue
        if _should_join(lines[i].text, lines[i + 1].text, family=family):
            label.join_next = True
            if label.confidence > 0.75:
                label.confidence = 0.75
    return labels


def uncertain_segment_indices(labels: list[LineLabel], *, threshold: float = 0.8) -> list[tuple[int, int]]:
    """Inclusive line-index ranges that need LLM review."""
    if not labels:
        return []
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for i, label in enumerate(labels):
        low = label.confidence < threshold or label.role == "verse_line"
        if low and start is None:
            start = i
        elif not low and start is not None:
            ranges.append((start, i - 1))
            start = None
    if start is not None:
        ranges.append((start, len(labels) - 1))
    merged: list[tuple[int, int]] = []
    for lo, hi in ranges:
        if merged and lo <= merged[-1][1] + 2:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged
