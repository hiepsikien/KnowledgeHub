"""Project Gutenberg table-of-contents detection for REF/1."""

from __future__ import annotations

import re

from .lines import TextLine
from .structure import CONTENTS_HEADER

IMPRINT_PUBLISHER = re.compile(
    r"^(?:REPRINTED|PRINTED|LONDON|NEW YORK|BOSTON|PHILADELPHIA|CAMBRIDGE|INDIANAPOLIS)\b",
    re.I,
)

CHAPTER_HEADING = re.compile(
    r"^(?:CHAPTER|CHAP\.?)\s+[IVXLC\d]+(?:\.\s*$|[.:]\s|\.\s|\s+[A-Z])",
    re.I,
)
BOOK_PART_HEADING = re.compile(
    r"^(?:BOOK|PART|VOLUME)\s+[IVXLC\d]+(?:[.:]\s|\.\s|\s+[A-Z])",
    re.I,
)
LETTER_CHAPTER_ENTRY = re.compile(
    r"^(?:Letter|LETTER|Chapter|CHAPTER)\s+\d+\.?\s*$",
    re.I,
)
ROMAN_ONLY = re.compile(r"^(?:[IVXLCDM]+|\d{1,3})$")
ALL_CAPS_SECTION = re.compile(r"^[A-Z][A-Z\s,\-\';]{15,95}[,.]?\s*$")
VI_TOC_HEADER = re.compile(r"^Mục\s+lục\b", re.I)
ELECTRONIC_NOTE = re.compile(r"^NOTE TO THIS ELECTRONIC EDITION\s*$", re.I)


def is_chapter_heading_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return bool(CHAPTER_HEADING.match(s) or BOOK_PART_HEADING.match(s))


def is_toc_list_row(line: str) -> bool:
    """TOC contents-list row (dot leaders / page number), not a body heading."""
    s = line.strip()
    if not s:
        return False
    if re.search(r"\.{2,}\s*\d{1,4}$", s):
        return True
    if re.search(r"\s{2,}\d{1,4}$", s) and len(s) < 90:
        return True
    return False


def is_all_caps_section_line(line: str) -> bool:
    s = line.strip()
    if not s or not ALL_CAPS_SECTION.match(s):
        return False
    if re.match(r"^(?:PHILADELPHIA|PRINTED|COMMON SENSE|INHABITANTS|AMERICA|MDCCL|ISBN)\b", s):
        return False
    return True


def is_all_caps_body_section_line(line: str) -> bool:
    """Strict ALL-CAPS body section (Paine pamphlet), not biography pull quotes."""
    s = line.strip()
    if not is_all_caps_section_line(s):
        return False
    upper = s.upper()
    if upper.startswith(("INTRODUCTION", "APPENDIX", "PREFACE", "EPILOGUE")):
        return True
    if re.match(r"^OF (?:THE|MONARCHY|THOUGHTS|A )", upper):
        return True
    if upper.startswith("THOUGHTS ON "):
        return True
    if s.endswith(",") and 28 <= len(s) <= 95:
        if re.search(r"\b(I|MY|WE|OUR|ME|TO)\b", upper):
            return False
        return True
    if re.search(r"\b(I|MY|WE|OUR|ME)\b", upper):
        return False
    if s.endswith(".") and len(s.split()) > 7 and "," not in s:
        return False
    return False


def is_body_heading_line(line: str) -> bool:
    """Standalone body section start — not a TOC list duplicate."""
    s = line.strip()
    if not s or len(s) > 160:
        return False
    if is_chapter_heading_line(s) and not is_toc_list_row(s):
        return True
    if re.match(r"^(?:PREFACE|INTRODUCTION|PROLOGUE|EPILOGUE|APPENDIX)\b", s, re.I):
        return not is_toc_list_row(s)
    return False


def is_chapter_title_line(line: str) -> bool:
    """Short title line following a CHAPTER row in a contents list."""
    s = line.strip()
    if not s or len(s) > 120 or is_chapter_heading_line(s):
        return False
    if re.search(r"\.{2,}\s*\d{1,4}$", s):
        return True
    if "—" in s or "–" in s or " - " in s:
        return True
    if len(s) < 90 and not re.search(r"[.!?]\s", s) and s.count(".") <= 1:
        return True
    return False


def is_toc_entry_line(line: str) -> bool:
    """True when a line looks like a contents-list row, not body prose."""
    s = line.strip()
    if not s or len(s) > 220:
        return False
    if re.match(r"^[\*\-–—_=\s]+$", s):
        return False
    if IMPRINT_PUBLISHER.match(s):
        return False
    if is_chapter_heading_line(s):
        return True
    if LETTER_CHAPTER_ENTRY.match(s):
        return True
    if ROMAN_ONLY.match(s) and len(s) <= 8:
        return True
    if re.match(r"^(?:BOOK|PART|VOLUME)\s+[IVXLC\d]+\b", s, re.I):
        return True
    if re.match(r"^SECT\.?\s+[IVXLC\d]+", s, re.I):
        return True
    if re.match(r"^\d+\.\s+\S", s):
        return True
    if re.search(r"\s{2,}\d{1,4}$", s) and len(s) < 90:
        return True
    if re.search(r"\.{2,}\s*\d{1,4}$", s) and len(s) < 90:
        return True
    return False


def _toc_run_should_stop_at_chapter_body(lines: list[TextLine], j: int) -> bool:
    """True when CHAPTER at j starts real body (not another TOC row)."""
    raw = lines[j].text.strip()
    if not is_chapter_heading_line(raw):
        return False
    k = j + 1
    while k < len(lines) and not lines[k].text.strip():
        k += 1
    if k >= len(lines):
        return False
    nxt = lines[k].text.strip()
    if len(nxt) < 55 or is_chapter_heading_line(nxt) or is_toc_entry_line(nxt):
        return False
    if is_chapter_title_line(nxt) or _is_toc_wrap_line(nxt):
        return False
    return bool(re.search(r"\bthe\b", nxt, re.I))


def _is_toc_wrap_line(line: str) -> bool:
    s = line.strip()
    if not s or is_chapter_heading_line(s) or len(s) > 100:
        return False
    return is_chapter_title_line(s) or (("—" in s or "–" in s) and len(s) < 100)


def is_toc_continuation(prev: str, nxt: str) -> bool:
    p = prev.strip()
    n = nxt.strip()
    if not p or not n:
        return False
    if is_chapter_heading_line(p) and is_chapter_title_line(n):
        return True
    if is_chapter_heading_line(n) or re.match(r"^(?:BOOK|PART|VOLUME)\s+[IVXLC\d]+\b", n, re.I):
        return False
    if p.endswith((".", "!", "?")) and not p.endswith("--"):
        if "—" in p or "–" in p:
            if len(n) < 100 and not is_chapter_heading_line(n):
                return True
        return False
    if n[0].islower():
        return True
    letters = [c for c in n if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) >= 0.85:
        return len(n) < 120
    return False


def _join_toc_lines(lines: list[TextLine], labels: list, start: int, end: int) -> None:
    indices = [k for k in range(start, end) if lines[k].text.strip()]
    for pos, k in enumerate(indices):
        labels[k].role = "toc"
        labels[k].level = 0
        labels[k].confidence = 0.93
        labels[k].join_next = pos < len(indices) - 1


def _consume_toc_run(lines: list[TextLine], labels: list, start: int) -> int:
    """Return index after a TOC run starting at start (inclusive)."""
    j = start
    toc_count = 0
    while j < len(labels):
        raw = lines[j].text.strip()
        if not raw:
            j += 1
            continue
        if is_toc_entry_line(raw) or (labels[j].role == "heading" and is_chapter_heading_line(raw)):
            if toc_count and _toc_run_should_stop_at_chapter_body(lines, j):
                break
            toc_count += 1
            j += 1
            continue
        if toc_count and _is_toc_wrap_line(raw):
            toc_count += 1
            j += 1
            continue
        if toc_count and is_toc_continuation(lines[j - 1].text, raw):
            toc_count += 1
            j += 1
            continue
        if toc_count and is_chapter_heading_line(raw):
            toc_count += 1
            j += 1
            if j < len(labels):
                nxt = lines[j].text.strip()
                if nxt and is_chapter_title_line(nxt):
                    toc_count += 1
                    j += 1
            continue
        break
    if toc_count >= 3:
        _join_toc_lines(lines, labels, start, j)
        return j
    return start + 1


def relabel_toc_runs(lines: list[TextLine], labels: list, *, family: str) -> None:
    if family not in {"gutenberg", "plain", "scholastic"}:
        return
    i = 0
    while i < len(labels):
        line = lines[i].text.strip()
        if CONTENTS_HEADER.match(line) or VI_TOC_HEADER.match(line):
            j = i + 1
            while j < len(labels):
                raw = lines[j].text.strip()
                if not raw:
                    j += 1
                    continue
                if is_toc_entry_line(raw) or is_chapter_heading_line(raw):
                    if j > i + 1 and _toc_run_should_stop_at_chapter_body(lines, j):
                        break
                    j += 1
                    if j < len(labels):
                        nxt = lines[j].text.strip()
                        if nxt and is_chapter_title_line(nxt):
                            j += 1
                    continue
                if is_toc_continuation(lines[j - 1].text, raw):
                    j += 1
                    continue
                if _is_toc_wrap_line(raw):
                    j += 1
                    continue
                break
            if j - i >= 2:
                _join_toc_lines(lines, labels, i, j)
                i = j
                continue
        if ELECTRONIC_NOTE.match(line):
            j = i + 1
            while j < len(labels):
                raw = lines[j].text.strip()
                if not raw:
                    j += 1
                    continue
                if is_hard_structural_line(raw):
                    break
                j += 1
            _join_toc_lines(lines, labels, i, j)
            i = j
            continue
        if not line or not (is_toc_entry_line(line) or (labels[i].role == "heading" and is_chapter_heading_line(line))):
            i += 1
            continue
        nxt_i = _consume_toc_run(lines, labels, i)
        i = nxt_i if nxt_i > i else i + 1


def is_hard_structural_line(line: str) -> bool:
    from .reflow import is_hard_structural

    return is_hard_structural(line.strip(), family="gutenberg")


def merge_split_chapter_titles(lines: list[TextLine], labels: list, *, family: str) -> None:
    if family != "gutenberg":
        return
    for i in range(len(labels) - 1):
        if labels[i].role in {"toc", "metadata"}:
            continue
        prev = lines[i].text.strip()
        nxt = lines[i + 1].text.strip()
        if not prev or not nxt:
            continue
        if not (labels[i].role == "heading" or is_chapter_heading_line(prev)):
            continue
        if is_chapter_heading_line(prev) and is_toc_continuation(prev, nxt):
            labels[i].join_next = True
            labels[i + 1].role = "heading"
            labels[i + 1].level = labels[i].level or 1
            labels[i + 1].confidence = 0.9
            continue
        if labels[i].role == "heading" and is_toc_continuation(prev, nxt):
            labels[i].join_next = True
            labels[i + 1].role = "heading"
            labels[i + 1].level = labels[i].level or 1
            labels[i + 1].confidence = 0.88
