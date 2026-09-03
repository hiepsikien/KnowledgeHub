"""Project Gutenberg table-of-contents detection for REF/1."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

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
    if re.search(r"\s{2,}(?:\d{1,4}|[ivxlcdm]{1,8})\s*$", s, re.I) and len(s) < 90:
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
    if re.match(
        r"^(?:(?:THE\s+)?(?:AUTHOR['’]S|TRANSLATOR['’]S|EDITOR['’]S|PUBLISHER['’]S)\s+)?"
        r"(?:PREFACE|INTRODUCTION|PROLOGUE|EPILOGUE|APPENDIX|CONCLUSION)\b",
        s,
        re.I,
    ):
        return not is_toc_list_row(s)
    if _UNIT_TOC_LINE.match(s):
        return not is_toc_list_row(s)
    if _SERIES_TOC_LINE.match(s):
        return not is_toc_list_row(s)
    numbered = _BARE_NUM_TITLE.match(s)
    if numbered and _looks_like_numbered_heading(numbered.group(2)):
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
    if re.search(r"\s{2,}(?:\d{1,4}|[ivxlcdm]{1,8})$", s, re.I) and len(s) < 90:
        return True
    if re.search(r"\.{2,}\s*\d{1,4}$", s) and len(s) < 90:
        return True
    # Compact PG lists: "Preface: iii-lx" / "I: 1-50 (Sweetness and Light)"
    # Require a full line — not a wrapped Bible cite like "33:23]".
    if (
        len(s) < 140
        and re.fullmatch(
            r"(?:Preface|Introduction|Prologue|Appendix|[IVXLCDM]+|\d{1,3})\s*:\s*"
            r"(?:[ivxlcdm]+|\d{1,4})(?:\s*[-–—]\s*(?:[ivxlcdm]+|\d{1,4}))?"
            r"(?:\s*\([^)]{0,80}\))?",
            s,
            re.I,
        )
    ):
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


CONTENTS_HEAD = re.compile(
    r"^(?:TABLE OF CONTENTS|CONTENTS(?: OF (?:THIS )?BOOK)?|MỤC LỤC)\s*\.?\s*$",
    re.I,
)


def toc_source_from_excerpt(excerpt: str) -> str:
    """Turn a curator-pasted TOC into a parseable Contents block.

    Only CONTENTS_HEAD is a parseable opener. Vietnamese ``Mục lục:`` matches
    VI_TOC_HEADER (body-run detector) but not CONTENTS_HEAD — prepend CONTENTS.
    """
    text = str(excerpt or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    first = next((ln.strip() for ln in text.split("\n") if ln.strip()), "")
    if CONTENTS_HEAD.match(first):
        return text
    return f"CONTENTS\n\n{text}"


_PAGE_COL = re.compile(r"^PAGE\s*$", re.I)
_CHAPTER_TOC_LINE = re.compile(r"^(?:CHAPTER|CHAP\.?)\s+([IVXLC\d]+)\.?\s*(.*)$", re.I)
_BOOK_PART_TOC_LINE = re.compile(r"^(BOOK|PART|VOLUME)\s+([IVXLC\d]+)\b(.*)$", re.I)
# Keyword is case-insensitive; the ordinal is not. re.I would make [A-Z] eat
# "Section of…" / "Essay in…" as unit O / I. Letter units (Sub-Section A.) need a
# period; roman/arabic may omit it but must be a whole token (not "Into").
_UNIT_TOC_LINE = re.compile(
    r"^(Essay|Section|Sub-Section|Subsection|Sub-section)\s+"
    r"((?-i:(?:[IVXLCDM]+|\d+)\.?(?=\s|$)|[A-Z]\.))\s*(.*)$",
    re.I,
)
_NAMED_TOC_LINE = re.compile(
    r"^(PREFACE|INTRODUCTION|PROLOGUE|FOREWORD|APPENDIX|NOTES|INDEX|"
    r"BIBLIOGRAPHY|GLOSSARY|ERRATA|FOOTNOTES|CONCLUSION|"
    r"CATALOGUE\b.*|CATALOG\b.*)\s*(.*)$",
    re.I,
)
_PREFIXED_FRONT_LINE = re.compile(
    r"^(?:THE\s+)?(?:AUTHOR['’]S|TRANSLATOR['’]S|EDITOR['’]S|PUBLISHER['’]S)\s+"
    r"(PREFACE|INTRODUCTION|FOREWORD|NOTE)\s*(.*)$",
    re.I,
)
_SERIES_TOC_LINE = re.compile(
    r"^(?:(.+?)\.\s+)?((?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)\s+SERIES)\.?\s*$",
    re.I,
)
_TITLE_CASE_SMALL = frozenset({"of", "and", "the", "or", "in", "a", "an", "to", "on", "for"})
_TOC_PAGE_TAIL = re.compile(r"(?:\.{2,}|\s{2,})(\d{1,4}|[ivxlcdm]{1,8})\s*$", re.I)
_TOC_STOP = re.compile(
    r"^(?:\*\*\*|List of |Illustrations\b|END OF THE PROJECT GUTENBERG)",
    re.I,
)
_STOP_WORDS = frozenset({"of", "the", "a", "an", "and", "or", "to", "in", "on", "for"})


def toc_page_tail(line: str) -> str | None:
    match = _TOC_PAGE_TAIL.search(line.strip())
    return match.group(1) if match else None


def strip_toc_page_tail(line: str) -> str:
    return _TOC_PAGE_TAIL.sub("", line.strip()).strip(" \t-–—.")


def kind_for_toc_label(label: str) -> str:
    u = (label or "").strip().upper()
    if u.startswith(("CHAPTER", "CHAP")):
        return "chapter"
    if u.startswith("BOOK"):
        return "book"
    if u.startswith(("PART", "VOLUME")):
        return "part"
    if u.startswith("ESSAY"):
        return "chapter"
    if u.startswith(("SUB-SECTION", "SUBSECTION", "SUB SECTION")):
        return "chapter"
    if u.startswith("SECTION"):
        return "part"
    if re.search(
        r"^(?:(?:THE\s+)?(?:AUTHOR['’]S|TRANSLATOR['’]S|EDITOR['’]S|PUBLISHER['’]S)\s+)?"
        r"(?:PREFACE|FOREWORD)\b",
        u,
    ):
        return "preface"
    if u.startswith("INTRODUCTION"):
        return "introduction"
    if u.startswith("PROLOGUE"):
        return "prologue"
    if u.startswith("APPENDIX"):
        return "appendix"
    if u.startswith(("NOTES", "INDEX", "BIBLIOGRAPHY", "GLOSSARY", "CATALOGUE", "CATALOG", "ERRATA", "FOOTNOTES")):
        return "back_matter"
    if re.search(r"\b(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)\s+SERIES\b", u):
        return "part"
    numbered = _BARE_NUM_TITLE.match((label or "").strip())
    if numbered and _looks_like_numbered_heading(numbered.group(2)):
        return "chapter"
    # Named essays stay "other" (not structural). toc_match still requires them
    # when the TOC has no chapter/book/part rows; Dedication / To the Reader
    # are filtered out of that fallback so they stay optional.
    return "other"


def chapter_number_key(label: str) -> str | None:
    match = re.match(r"^(?:chapter|chap\.?)\s+([ivxlcdm]+|\d+)\b", (label or "").strip(), re.I)
    if not match:
        return None
    num = match.group(1)
    if num.isdigit():
        value = int(num)
        return str(value) if value > 0 else None
    value = _roman_to_int(num.upper())
    return str(value) if value else None


def _roman_to_int(token: str) -> int | None:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    if not token or any(ch not in values for ch in token):
        return None
    total = 0
    prev = 0
    for ch in reversed(token):
        val = values[ch]
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    return total if total > 0 else None


def _is_title_case_heading(line: str) -> bool:
    """Standalone title-case TOC row without CHAPTER/Essay and without a page column."""
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if toc_page_tail(s) or is_toc_list_row(s):
        return False
    if (
        _CHAPTER_TOC_LINE.match(s)
        or _NAMED_TOC_LINE.match(s)
        or _UNIT_TOC_LINE.match(s)
        or _BOOK_PART_TOC_LINE.match(s)
    ):
        return False
    core = s.rstrip(".")
    if not core or not core[0].isalpha() or not core[0].isupper():
        return False
    words = re.findall(r"[A-Za-z']+", core)
    if not words:
        return False
    letters = [c for c in core if c.isalpha()]
    # ALL-CAPS column headers / body reprints (NUMBERS;, CHAPTER PAGE, I.)
    if letters and sum(c.isupper() for c in letters) / len(letters) >= 0.85:
        return False
    for word in words:
        if word.lower() in _TITLE_CASE_SMALL:
            continue
        if not word[0].isupper():
            return False
    return True


def _looks_like_numbered_heading(rest: str) -> bool:
    """True for TOC/body titles after ``I.`` / ``12.``, not numbered prose."""
    raw = strip_toc_page_tail(rest).strip()
    if not raw or len(raw) > 180:
        return False
    letters = [c for c in raw if c.isalpha()]
    if not letters:
        return False
    if sum(c.isupper() for c in letters) / len(letters) >= 0.75:
        return True
    return _is_title_case_heading(raw)


def _numbered_toc_match(line: str) -> re.Match[str] | None:
    match = _BARE_NUM_TITLE.match(line.strip())
    if match and _looks_like_numbered_heading(match.group(2)):
        return match
    return None


def _is_new_toc_row(line: str) -> bool:
    s = line.strip()
    return bool(
        _CHAPTER_TOC_LINE.match(s)
        or _NAMED_TOC_LINE.match(s)
        or _PREFIXED_FRONT_LINE.match(s)
        or _BOOK_PART_TOC_LINE.match(s)
        or _UNIT_TOC_LINE.match(s)
        or _SERIES_TOC_LINE.match(s)
        or _numbered_toc_match(s)
    )


def _following_has_toc_wrap_page(lines: list[str], index: int) -> bool:
    """True when a bare CHAPTER line is followed by a synopsis that ends in a page number."""
    for j in range(index + 1, min(index + 14, len(lines))):
        nxt = lines[j].strip()
        if not nxt:
            continue
        if _is_new_toc_row(nxt) or _TOC_STOP.match(nxt):
            return False
        if toc_page_tail(nxt) or is_toc_list_row(nxt):
            return True
    return False


def _following_is_toc_title_wrap(lines: list[str], index: int) -> bool:
    """True when the next TOC line continues this title (page column or short wrap)."""
    if _following_has_toc_wrap_page(lines, index):
        return True
    for j in range(index + 1, min(index + 4, len(lines))):
        nxt = lines[j].strip()
        if not nxt:
            continue
        if _is_new_toc_row(nxt) or _TOC_STOP.match(nxt):
            return False
        return len(nxt) < 50
    return False


def toc_is_wrap_page_column(entries: list[dict[str, Any]]) -> bool:
    """CHAPTER-on-its-own-line wrap TOC (Abdy leftover stubs), with or without a page column.

    Austen ``CHAPTER I. Title  1`` one-liners are not wrapped and stay on markers.
    """
    if len(entries) < 3:
        return False
    wrapped = sum(1 for e in entries if e.get("wrapped"))
    paged = sum(1 for e in entries if e.get("page"))
    if wrapped >= 2 and paged >= 2:
        return True
    if wrapped < 2:
        return False
    numbered = sum(1 for e in entries if chapter_number_key(str(e.get("label") or "")))
    return numbered >= 3


def toc_is_page_column_map(entries: list[dict[str, Any]]) -> bool:
    """Use TOC→body for page-column Contents maps, except numbered CHAPTER one-liners.

    Arnold-style named essays (`Numbers … 1`) need the map; Austen `CHAPTER I. Title  1`
    stays on markers.
    """
    if toc_is_wrap_page_column(entries):
        return True
    if len(entries) < 2:
        return False
    paged = sum(1 for e in entries if e.get("page"))
    if paged < 2:
        return False
    numbered = sum(1 for e in entries if chapter_number_key(str(e.get("label") or "")))
    return numbered < max(2, (len(entries) + 1) // 2)


def toc_is_heading_list_map(entries: list[dict[str, Any]]) -> bool:
    """Named heading list without a page column (Hegel essays / sections).

    Austen ``CHAPTER I.`` one-liners stay on markers: they are mostly numbered
    CHAPTER rows. Arnold/Abdy page-column maps use ``toc_is_page_column_map``.
    """
    if len(entries) < 4:
        return False
    paged = sum(1 for e in entries if e.get("page"))
    if paged >= 2:
        return False
    structural = sum(1 for e in entries if e.get("kind") in _STRUCTURAL_TOC_KINDS)
    if structural < 3:
        return False
    numbered = sum(1 for e in entries if chapter_number_key(str(e.get("label") or "")))
    return numbered < max(2, (len(entries) + 1) // 2)


# Catalogue / glossary / bibliography are optional. A miss still allows toc_match;
# that tail stays in the previous section. Require every chapter/part/book/preface.
_STRUCTURAL_TOC_KINDS = frozenset({"chapter", "part", "book", "preface", "introduction", "prologue"})
_OPTIONAL_TOC_FRONT = re.compile(r"^(DEDICATION|TO THE READER|ADVERTISEMENT)\b", re.I)


def toc_match_covers_structure(
    entries: list[dict[str, Any]],
    matched: list[dict[str, Any]],
) -> bool:
    """Require every structural TOC entry; unmatched back_matter is allowed."""
    if not entries or not matched:
        return False
    needed = [e for e in entries if e.get("kind") in _STRUCTURAL_TOC_KINDS]
    if not needed:
        needed = [
            e
            for e in entries
            if not _OPTIONAL_TOC_FRONT.match(str(e.get("label") or "").strip())
        ]
        if not needed:
            needed = list(entries)
    got = {(m.get("index"), m.get("label")) for m in matched}
    return all((e.get("index"), e.get("label")) in got for e in needed)


_TOC_CHAPTER_BARE = re.compile(r"^(?:CHAPTER|CHAP\.?)\s+[IVXLC\d]+\.?\s*$", re.I)
_TOC_CHAPTER_ANY = re.compile(r"^(?:CHAPTER|CHAP\.?)\s+[IVXLC\d]+", re.I)


def _looks_like_chapter_body_prose(line: str) -> bool:
    """Substantial body paragraph after CHAPTER — not a contents title/synopsis.

    A finished sentence (``.!?``) or a long line without a title/synopsis shape
    counts as body. Leftover CONTENTS synopses are dash-lists of topics (two or
    more dashes, or one dash with no terminal period). ``the`` is a useful
    signal in fixtures but is not required — Austen-style openings omit it.
    """
    s = line.strip()
    if not s or len(s) < 55:
        return False
    if _TOC_CHAPTER_ANY.match(s) or is_chapter_heading_line(s):
        return False
    dash_hits = s.count("—") + s.count("–") + s.count("--")
    ends_sentence = bool(re.search(r"[.!?]$", s))
    if dash_hits >= 2:
        return False
    if dash_hits == 1:
        return ends_sentence
    if is_chapter_title_line(s) and not ends_sentence:
        return False
    return True


def _is_toc_stub_follow_line(line: str) -> bool:
    """Title/synopsis after a leftover CHAPTER row (dashes, page, or no sentence end)."""
    s = line.strip()
    if not s:
        return False
    if is_toc_list_row(s) or toc_page_tail(s):
        return True
    if "—" in s or "–" in s or "--" in s:
        return True
    if (is_chapter_title_line(s) or _is_toc_wrap_line(s)) and not re.search(r"[.!?]$", s):
        return True
    return False


def _join_chapter_follow_lines(lines: list[str], start: int, *, limit: int) -> str:
    """Join wrap continuations after a CHAPTER line (lowercase / TOC wrap)."""
    parts: list[str] = []
    end = min(start + limit, len(lines))
    for j in range(start, end):
        nxt = lines[j].strip()
        if not nxt:
            if parts:
                break
            continue
        if _TOC_CHAPTER_ANY.match(nxt):
            break
        if parts and not (nxt[0:1].islower() or is_toc_continuation(parts[-1], nxt)):
            break
        parts.append(nxt)
        if toc_page_tail(nxt) or is_toc_list_row(nxt):
            break
    return " ".join(parts)


def is_toc_chapter_block(lines: list[str], index: int) -> bool:
    """True when this CHAPTER line is a contents stub, not body.

    Leftover CONTENTS rows are bare ``CHAPTER N`` (optional period) with a
    title/synopsis and maybe a page, then the next CHAPTER. Real body is the
    same marker followed by a substantial prose paragraph (function word
    ``the``, not another CHAPTER / title line). Consecutive bare CHAPTER
    lines with only blanks between them are a TOC list.
    """
    if index < 0 or index >= len(lines):
        return False
    stripped = lines[index].strip()
    if not _TOC_CHAPTER_BARE.match(stripped):
        return False
    seen = 0
    saw_toc_material = False
    j = index + 1
    end = min(index + 14, len(lines))
    while j < end:
        nxt = lines[j].strip()
        if not nxt:
            j += 1
            continue
        if _TOC_CHAPTER_ANY.match(nxt):
            # Only blanks → TOC list. Synopsis/title then CHAPTER → leftover stub.
            # A short sentence then CHAPTER is body (Austen / nested BOOK+CHAPTER).
            return seen == 0 or saw_toc_material
        seen += 1
        blob = _join_chapter_follow_lines(lines, j, limit=end - j)
        if (
            is_toc_list_row(nxt)
            or toc_page_tail(nxt)
            or is_toc_list_row(blob)
            or toc_page_tail(blob)
        ):
            return True
        if _looks_like_chapter_body_prose(blob) or _looks_like_chapter_body_prose(nxt):
            return False
        if _is_toc_stub_follow_line(nxt) or _is_toc_stub_follow_line(blob):
            saw_toc_material = True
            j += 1
            if seen >= 8:
                return False
            continue
        if seen >= 8:
            return False
        j += 1
    return False


_FOOTNOTE_MARK = re.compile(r"\[\d+\]")
_BARE_NUM_TITLE = re.compile(r"^([IVXLC]{1,8}|\d+)\.\s+(.+)$")
_BARE_NUM_ONLY = re.compile(r"^[IVXLC]{1,8}\.$")


def is_chapter_number_only_line(line: str) -> bool:
    """Lone roman numeral heading (``I.``, ``XII.``), not ``CHAPTER I`` or a year."""
    return bool(_BARE_NUM_ONLY.fullmatch(line.strip()))


def strip_heading_number(text: str) -> str:
    """Drop a leading bare roman/arabic ordinal so titles can match across series."""
    s = _FOOTNOTE_MARK.sub("", text or "").strip()
    match = _BARE_NUM_TITLE.match(s)
    if match:
        return match.group(2).strip()
    return s


def bare_leading_numeral(text: str) -> str | None:
    """Roman/arabic ordinal at the start of a named-essay heading, not CHAPTER/BOOK."""
    s = (text or "").strip()
    if re.match(r"^(?:CHAPTER|CHAP\.?|BOOK|PART|VOLUME)\b", s, re.I):
        return None
    match = re.match(r"^([IVXLC]{1,8}|\d+)\.(?:\s|$)", s)
    if not match:
        return None
    token = match.group(1)
    return token if token.isdigit() else token.upper()


def _norm_toc_heading(text: str) -> str:
    s = _FOOTNOTE_MARK.sub(" ", text or "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("\u00a0", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _title_key(text: str) -> str:
    return _norm_toc_heading(strip_heading_number(text))


def _sig_tokens(text: str) -> set[str]:
    return {p for p in _norm_toc_heading(text).split() if p not in _STOP_WORDS and len(p) > 1}


def _int_to_roman(value: int) -> str:
    table = (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    parts: list[str] = []
    n = value
    for amount, glyph in table:
        while n >= amount:
            parts.append(glyph)
            n -= amount
    return "".join(parts)


def _match_strings_for(label: str, title: str) -> list[str]:
    out: list[str] = []
    for val in (label, title):
        val = (val or "").strip()
        if val:
            out.append(val)
            stripped = strip_heading_number(val)
            if stripped and stripped != val:
                out.append(stripped)
    num = chapter_number_key(label)
    if num:
        tokens = [num]
        roman = _int_to_roman(int(num))
        if roman and roman != num:
            tokens.append(roman)
        for token in tokens:
            out.extend(
                [f"CHAPTER {token}", f"Chapter {token}", f"CHAPTER {token}.", f"Chapter {token}."]
            )
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        key = _norm_toc_heading(item)
        if key and key not in seen:
            seen.add(key)
            uniq.append(item)
    return uniq


def _flush_toc_pending(pending: dict[str, Any] | None, entries: list[dict[str, Any]]) -> None:
    if not pending:
        return
    title = re.sub(r"\s+", " ", " ".join(pending.get("title_parts") or [])).strip()
    title = strip_toc_page_tail(title)
    label = str(pending.get("label") or title or "Section")
    entries.append(
        {
            "index": len(entries) + 1,
            "label": label,
            "title": title or label,
            "kind": str(pending.get("kind") or kind_for_toc_label(label)),
            "page": pending.get("page"),
            "wrapped": bool(pending.get("wrapped")),
            "match_strings": _match_strings_for(label, title),
        }
    )


def parse_contents_entries(text: str) -> list[dict[str, Any]]:
    """Structured body entries from a Contents / Table of Contents block."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start: int | None = None
    for i, line in enumerate(lines):
        if CONTENTS_HEAD.match(line.strip()):
            start = i
            break
    if start is None:
        return []

    entries: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal pending
        _flush_toc_pending(pending, entries)
        pending = None

    for index in range(start + 1, min(start + 450, len(lines))):
        stripped = lines[index].strip()
        if not stripped or _PAGE_COL.match(stripped):
            continue
        if _TOC_STOP.match(stripped):
            flush()
            break

        chapter = _CHAPTER_TOC_LINE.match(stripped)
        if chapter:
            rest = chapter.group(2).strip()
            page = toc_page_tail(stripped)
            word0 = stripped.split()[0]
            num = chapter.group(1)
            label = f"CHAPTER {num.upper() if not num.isdigit() else num}"
            already = chapter_number_key(label)
            if entries and _TOC_CHAPTER_BARE.match(stripped) and not is_toc_chapter_block(lines, index):
                # Body ``Chapter N`` / ``CHAPTER N`` + prose — leftover stubs stay open.
                flush()
                break
            if (
                entries
                and pending is None
                and (
                    (word0[:1].isupper() and word0[1:].islower())
                    or already in {chapter_number_key(str(e.get("label") or "")) for e in entries}
                    or (
                        not rest
                        and not page
                        and not _following_has_toc_wrap_page(lines, index)
                    )
                )
            ):
                break
            flush()
            pending = {
                "label": label,
                "kind": "chapter",
                "title_parts": [strip_toc_page_tail(rest)] if rest and strip_toc_page_tail(rest) else [],
                "page": page,
                "wrapped": False,
            }
            if page:
                flush()
            continue

        prefixed = _PREFIXED_FRONT_LINE.match(stripped)
        if prefixed:
            named = prefixed
        else:
            named = _NAMED_TOC_LINE.match(stripped)
        if named:
            full = strip_toc_page_tail(stripped)
            kind = kind_for_toc_label(full or named.group(1))
            page = toc_page_tail(stripped)
            head = str(named.group(1) or "").upper()
            if (
                entries
                and pending is None
                and kind not in {"back_matter", "appendix"}
                and any(
                    str(e.get("label") or "").upper().startswith(head) and e.get("kind") == kind
                    for e in entries
                )
                and not page
                and not _following_has_toc_wrap_page(lines, index)
            ):
                flush()
                break
            flush()
            pending = {
                "label": full or named.group(1),
                "kind": kind,
                "title_parts": [],
                "page": page,
            }
            # Flush immediately unless a wrap title + page column follows (Abdy PREFACE).
            if pending["page"] or not _following_has_toc_wrap_page(lines, index):
                flush()
            continue

        unit = _UNIT_TOC_LINE.match(stripped)
        if unit:
            flush()
            full = strip_toc_page_tail(stripped)
            rest = unit.group(3).strip()
            page = toc_page_tail(stripped)
            pending = {
                "label": full,
                "kind": kind_for_toc_label(full),
                "title_parts": [strip_toc_page_tail(rest)] if rest and strip_toc_page_tail(rest) else [],
                "page": page,
                "wrapped": False,
            }
            if pending["page"] or rest or not _following_has_toc_wrap_page(lines, index):
                flush()
            continue

        book_part = _BOOK_PART_TOC_LINE.match(stripped)
        if book_part:
            flush()
            unit_name = book_part.group(1).upper()
            num = book_part.group(2)
            rest = book_part.group(3).strip()
            label = f"{unit_name} {num.upper() if not num.isdigit() else num}"
            pending = {
                "label": label,
                "kind": "book" if unit_name == "BOOK" else "part",
                "title_parts": [strip_toc_page_tail(rest)] if rest and strip_toc_page_tail(rest) else [],
                "page": toc_page_tail(stripped),
            }
            if pending["page"] and not rest:
                flush()
            continue

        series = _SERIES_TOC_LINE.match(stripped)
        if series:
            flush()
            full = strip_toc_page_tail(stripped)
            pending = {
                "label": full,
                "kind": "part",
                "title_parts": [],
                "page": toc_page_tail(stripped),
            }
            if pending["page"] or not _following_is_toc_title_wrap(lines, index):
                flush()
            continue

        numbered = _numbered_toc_match(stripped)
        if numbered:
            flush()
            full = strip_toc_page_tail(stripped)
            page = toc_page_tail(stripped)
            pending = {
                "label": full,
                "kind": "chapter",
                "title_parts": [full],
                "page": page,
                "wrapped": False,
            }
            if page or not _following_is_toc_title_wrap(lines, index):
                flush()
            continue

        if pending is not None:
            pending.setdefault("title_parts", []).append(strip_toc_page_tail(stripped))
            pending["wrapped"] = True
            page = toc_page_tail(stripped)
            if page:
                pending["page"] = page
                flush()
            continue

        page = toc_page_tail(stripped)
        if page and len(stripped) < 90:
            label = strip_toc_page_tail(stripped)
            if label:
                entries.append(
                    {
                        "index": len(entries) + 1,
                        "label": label,
                        "title": label,
                        "kind": kind_for_toc_label(label),
                        "page": page,
                        "match_strings": _match_strings_for(label, label),
                    }
                )
            continue

        if _is_title_case_heading(stripped):
            # Only inside a title-list TOC (Preface / Essay / Section, no page column).
            # Page-column maps must not ingest ALL-CAPS body reprints as extra rows.
            if not entries or any(e.get("page") for e in entries):
                continue
            label = strip_toc_page_tail(stripped)
            already = {_norm_toc_heading(str(e.get("label") or "")) for e in entries}
            if label and _norm_toc_heading(label) not in already:
                entries.append(
                    {
                        "index": len(entries) + 1,
                        "label": label,
                        "title": label,
                        "kind": kind_for_toc_label(label),
                        "page": None,
                        "match_strings": _match_strings_for(label, label),
                    }
                )
            continue

        if entries and len(stripped) > 90 and not page:
            break

    flush()
    return entries


def format_contents_excerpt(entries: list[dict[str, Any]], *, max_chars: int = 12000) -> str:
    rows: list[str] = ["CONTENTS"]
    for entry in entries:
        label = str(entry.get("label") or "")
        title = str(entry.get("title") or "")
        if title and title.upper() != label.upper() and not title.upper().startswith(label.upper()):
            line = f"{label}  {title}"
        else:
            line = label
        rows.append(line)
        if sum(len(x) + 1 for x in rows) > max_chars:
            break
    return "\n".join(rows)[:max_chars]


def _is_titleish_line(line: str) -> bool:
    s = line.strip()
    if not s or is_toc_list_row(s):
        return False
    numbered = _BARE_NUM_TITLE.match(s)
    if numbered and _looks_like_numbered_heading(numbered.group(2)) and len(s) <= 120:
        return True
    if len(s) > 80:
        return False
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    if sum(c.isupper() for c in letters) / len(letters) >= 0.75:
        return True
    words = [w for w in s.strip(".;:").split() if w]
    if 1 <= len(words) <= 10 and all(w[:1].isupper() for w in words if w[:1].isalpha()):
        return not re.search(r"[.!?]\s+\S", s) and len(s) < 70
    return False


def _joined_title_window(lines: list[str], start: int, *, limit: int = 4) -> str:
    """Join a split all-caps heading such as NUMBERS; / OR, / THE MAJORITY…"""
    parts: list[str] = []
    span = limit
    if start < len(lines) and is_chapter_number_only_line(lines[start]):
        span = limit + 2
    for j in range(start, min(start + span, len(lines))):
        s = lines[j].strip()
        if not s:
            # Arnold second series: ``I.`` then a blank then ``THE STUDY OF POETRY.``
            if len(parts) == 1 and is_chapter_number_only_line(parts[0]):
                continue
            if parts:
                break
            continue
        if is_toc_list_row(s) or is_toc_chapter_block(lines, j):
            break
        if not _is_titleish_line(s):
            break
        parts.append(s)
        joined = " ".join(parts)
        if s.endswith(".") and len(_norm_toc_heading(joined).split()) >= 3:
            break
    return " ".join(parts)


def _attach_leading_chapter_number(lines: list[str], found_line: int) -> int:
    """If the matched title follows a lone roman numeral, start the section there.

    Only attach when the previous non-empty line is itself a chapter number — never
    glue a numeral onto following prose.
    """
    if found_line <= 0 or found_line >= len(lines):
        return found_line
    if is_chapter_number_only_line(lines[found_line]):
        return found_line
    j = found_line - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j < 0 or not is_chapter_number_only_line(lines[j].strip()):
        return found_line
    following = lines[found_line].strip()
    if not _is_titleish_line(following):
        return found_line
    return j


def heading_title_from_toc_match(row: dict[str, Any]) -> str:
    """Prefer the TOC label when the body reprint uses a different ordinal."""
    toc_label = str(row.get("label") or "").strip()
    body = str(row.get("text") or "").strip()
    toc_num = bare_leading_numeral(toc_label)
    body_num = bare_leading_numeral(body)
    if toc_num and toc_num != body_num:
        chosen = toc_label
    else:
        chosen = body or toc_label
    return _FOOTNOTE_MARK.sub("", chosen).strip()


def match_toc_entries_in_body(text: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Locate TOC entries on body heading lines, skipping leftover contents-list rows."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    matched: list[dict[str, Any]] = []
    cursor = -1
    for entry in entries:
        chap = chapter_number_key(str(entry.get("label") or ""))
        needles = [
            key
            for s in (entry.get("match_strings") or [])
            if s
            for key in (_title_key(s), _norm_toc_heading(s))
            if key
        ]
        need_toks = _sig_tokens(strip_heading_number(str(entry.get("label") or ""))) | _sig_tokens(
            strip_heading_number(str(entry.get("title") or ""))
        )
        found_line: int | None = None
        found_text = ""
        hit_line: int | None = None
        for line_no, raw in enumerate(lines):
            if line_no <= cursor:
                continue
            raw_line = raw.strip()
            if not raw_line or len(raw_line) > 120:
                continue
            if is_toc_list_row(raw_line) or is_toc_chapter_block(lines, line_no):
                continue
            if chap:
                got = chapter_number_key(raw_line)
                if got == chap:
                    found_line = line_no
                    found_text = raw_line
                    hit_line = line_no
                    break
                continue
            if is_chapter_number_only_line(raw_line):
                continue
            probes = [raw_line]
            joined = _joined_title_window(lines, line_no)
            if joined and joined != raw_line:
                probes.append(joined)
            hit = False
            hit_text = raw_line
            for probe in probes:
                if is_chapter_number_only_line(probe):
                    continue
                title_key = _title_key(probe)
                norm = _norm_toc_heading(probe)
                if not title_key and not norm:
                    continue
                if any(n in {title_key, norm} for n in needles):
                    hit = True
                    hit_text = probe
                    break
                probe_toks = _sig_tokens(strip_heading_number(probe))
                if len(need_toks) >= 2 and need_toks <= probe_toks and len(probe) < 120:
                    hit = True
                    hit_text = probe
                    break
            if hit:
                found_line = _attach_leading_chapter_number(lines, line_no)
                found_text = hit_text
                if found_line < line_no:
                    numeral = lines[found_line].strip()
                    if numeral and numeral not in found_text:
                        found_text = f"{numeral} {found_text}".strip()
                hit_line = line_no
                break
        if found_line is None:
            continue
        item = dict(entry)
        item["line"] = found_line
        item["text"] = found_text
        matched.append(item)
        # Advance past the matched title, not the attached numeral. Otherwise the
        # next entry can still see this title (token-subset false match).
        cursor = hit_line if hit_line is not None else found_line
    return matched
