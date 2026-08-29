from __future__ import annotations

import re
from dataclasses import dataclass

from .lines import TextLine
from .reflow import ORDINAL_WRAP, is_all_caps_heading, is_hard_structural, is_soft_structural

RULE_LINE = re.compile(r"^[\-–—_\*=\s]{8,}$")
SHORT_RULE_LINE = re.compile(r"^[\-–—_\*=\s]{3,7}$")
ITALIC_LINE = re.compile(r"^_([^_].*[^_])_$")
SENTENCE_END = re.compile(r"""[.!?](?:\[?\d{1,4}\]?|[\"'\])])*$|[\]\)”»][\"'\])]*$""")
CONTINUATION_START = re.compile(r"^[a-z(\[\"“‘«_]")
HYPHEN_BREAK = re.compile(r"-$")
QUOTE_LINE = re.compile(r'^[“"‘«_].*[”"’»_]?')
COMPLETE_QUOTE = re.compile(r'(?:[”"\'»_]|etc\.)\]?\.?\[\d{1,4}\]$')
BRIDGE_LINE = re.compile(r"^and in (?:another place|this wise):$", re.I)
LEAD_IN_LINE = re.compile(r"^[A-Z][A-Za-zÀ-ỹ .,''-]{0,40}:$")
HANGING_WORD = re.compile(
    r"\b(?:the|a|an|of|in|to|for|and|or|as|at|by|with|from|that|which|who|whom|whose|but|not|if|on|"
    r"her|his|its|their|our|my|your|this|these|those|such|some|any|each|every|both|all|other|"
    r"into|through|over|under|between|among|upon|de|du|des|la|le|les|un|une|một|của|và|là|trong|trên|"
    r"với|từ|để|này|đó|các|những)\s*$",
    re.I,
)
IMPRINT_PUBLISHER = re.compile(
    r"^(?:REPRINTED|PRINTED|LONDON|NEW YORK|BOSTON|PHILADELPHIA|CAMBRIDGE|INDIANAPOLIS)\b",
    re.I,
)
IMPRINT_LIST = re.compile(r"^.*,.*(?:1\.|[A-Z]\.)")
IMPRINT_ABBREV_END = re.compile(r"\b[A-Z]\.$")
ROMAN_YEAR = re.compile(r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")


def _is_imprint_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if IMPRINT_PUBLISHER.match(s) or IMPRINT_LIST.match(s) or ROMAN_YEAR.fullmatch(s):
        return True
    if s.count(",") >= 3 and len(s) >= 30:
        letters = [c for c in s if c.isascii() and c.isalpha()]
        if len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) >= 0.7:
            return True
    return False


def _sentence_ended(prev: str) -> bool:
    prev_r = prev.rstrip()
    if IMPRINT_ABBREV_END.search(prev_r):
        return False
    return bool(SENTENCE_END.search(prev_r))


def _continues_quoted_line(prev: str, nxt: str) -> bool:
    p = prev.strip()
    n = nxt.strip()
    if not p or not n:
        return False
    if not (p.startswith(('"', "“", "«", "_")) or "“" in p or "«" in p):
        return False
    if COMPLETE_QUOTE.search(p):
        return False
    if SENTENCE_END.search(p) and not p.endswith((",", ";", ":", "--")):
        return False
    return True


def _role_for_line(line: str, *, family: str) -> tuple[str, int, float]:
    if RULE_LINE.match(line) or SHORT_RULE_LINE.match(line.strip()):
        return "hr", 0, 0.98
    if IMPRINT_PUBLISHER.match(line.strip()) or IMPRINT_LIST.match(line.strip()):
        return "prose", 0, 0.9
    if is_hard_structural(line, family=family):
        level = 1 if re.match(r"^(?:CHAPTER|BOOK|PART|VOLUME)\b", line, re.I) else 2
        return "heading", level, 0.95
    if is_soft_structural(line, family=family):
        return "heading", 3, 0.9
    if ITALIC_LINE.match(line):
        return "heading", 2, 0.88
    if is_all_caps_heading(line):
        return "heading", 2, 0.82
    if QUOTE_LINE.match(line.strip()) and len(line.strip()) < 220:
        return "verse_line", 0, 0.86
    return "prose", 0, 0.92


def _should_join(prev: str, nxt: str, *, family: str, blank_before: bool = False) -> bool:
    prev_r = prev.rstrip()
    nxt_s = nxt.strip()
    spurious_blank = (
        blank_before
        and HANGING_WORD.search(prev_r)
        and not _sentence_ended(prev)
    )
    imprint_blank = (
        blank_before
        and family == "gutenberg"
        and (_is_imprint_line(prev_r) or _is_imprint_line(nxt_s))
    )
    if blank_before and not spurious_blank and not imprint_blank:
        return False
    if is_hard_structural(nxt, family=family) or is_soft_structural(nxt, family=family):
        return False
    if RULE_LINE.match(nxt) or SHORT_RULE_LINE.match(nxt_s):
        return False
    if BRIDGE_LINE.match(nxt_s) or LEAD_IN_LINE.match(nxt_s):
        return False
    if COMPLETE_QUOTE.search(prev.strip()):
        return False
    if spurious_blank and re.match(r"^[A-Za-z(\[\"]", nxt_s):
        return True
    if (
        family == "gutenberg"
        and _is_imprint_line(prev_r)
        and (
            _is_imprint_line(nxt_s)
            or ROMAN_YEAR.fullmatch(nxt_s)
            or nxt_s.startswith(("AND ", "and "))
        )
    ):
        return True
    if _continues_quoted_line(prev, nxt):
        return True
    if (
        len(prev) >= ORDINAL_WRAP
        and HANGING_WORD.search(prev_r)
        and not _sentence_ended(prev)
    ):
        return True
    if HYPHEN_BREAK.search(prev_r) and nxt[:1].islower():
        return True
    if CONTINUATION_START.match(nxt) and not _sentence_ended(prev):
        return True
    if len(prev) >= ORDINAL_WRAP and not _sentence_ended(prev) and CONTINUATION_START.match(nxt):
        return True
    if (
        len(prev_r) >= ORDINAL_WRAP
        and not _sentence_ended(prev)
        and re.match(r"^[A-Z]", nxt_s)
        and not nxt_s.startswith(("CHAPTER", "BOOK", "PART", "QUESTION", "ACT ", "SCENE"))
    ):
        return True
    if prev_r.endswith((",", ";", "--")) and CONTINUATION_START.match(nxt):
        return True
    if prev_r.endswith(":") and nxt_s.startswith(('"', "“", "_", "«")):
        return True
    return False


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


def _relabel_quote_continuations(lines: list[TextLine], labels: list[LineLabel]) -> None:
    for i in range(1, len(labels)):
        if labels[i].role != "prose":
            continue
        prev = lines[i - 1].text
        curr = lines[i].text
        if labels[i - 1].role == "verse_line" and _continues_quoted_line(prev, curr):
            labels[i].role = "verse_line"
            labels[i].confidence = 0.84
        elif labels[i - 1].role == "verse_line" and not SENTENCE_END.search(prev.strip()):
            labels[i].role = "verse_line"
            labels[i].confidence = 0.82


def label_lines_rules(lines: list[TextLine], *, family: str = "gutenberg") -> list[LineLabel]:
    labels: list[LineLabel] = []
    for row in lines:
        role, level, confidence = _role_for_line(row.text, family=family)
        labels.append(
            LineLabel(index=row.index, role=role, level=level, confidence=confidence)
        )
    _relabel_quote_continuations(lines, labels)
    for i in range(len(labels) - 1):
        if labels[i].role == "verse_line" and labels[i + 1].role == "verse_line":
            if not COMPLETE_QUOTE.search(lines[i].text.strip()):
                labels[i].join_next = True
    for i, label in enumerate(labels):
        if label.role not in {"prose", "verse_line"}:
            continue
        if i + 1 >= len(labels):
            continue
        nxt = labels[i + 1]
        if nxt.role == "verse_line" and LEAD_IN_LINE.match(lines[i].text.strip()):
            label.join_next = True
            continue
        if nxt.role not in {"prose", "verse_line"}:
            continue
        if _should_join(
            lines[i].text,
            lines[i + 1].text,
            family=family,
            blank_before=lines[i + 1].blank_before,
        ):
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
