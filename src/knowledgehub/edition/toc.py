"""Project Gutenberg table-of-contents detection for REF/1."""

from __future__ import annotations

import re
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
    if re.search(r"\s{2,}(?:\d{1,4}|[ivxlcdm]{1,8})$", s, re.I) and len(s) < 90:
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


CONTENTS_HEAD = re.compile(
    r"^(?:TABLE OF CONTENTS|CONTENTS(?: OF (?:THIS )?BOOK)?|MỤC LỤC)\s*\.?\s*$",
    re.I,
)
_PAGE_COL = re.compile(r"^PAGE\s*$", re.I)
_CHAPTER_TOC_LINE = re.compile(r"^(?:CHAPTER|CHAP\.?)\s+([IVXLC\d]+)\.?\s*(.*)$", re.I)
_BOOK_PART_TOC_LINE = re.compile(r"^(BOOK|PART|VOLUME)\s+([IVXLC\d]+)\b(.*)$", re.I)
_NAMED_TOC_LINE = re.compile(
    r"^(PREFACE|INTRODUCTION|PROLOGUE|FOREWORD|APPENDIX|NOTES|INDEX|"
    r"BIBLIOGRAPHY|GLOSSARY|ERRATA|CATALOGUE\b.*|CATALOG\b.*)\s*(.*)$",
    re.I,
)
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
    if u.startswith("PREFACE") or "FOREWORD" in u:
        return "preface"
    if u.startswith("INTRODUCTION"):
        return "introduction"
    if u.startswith("PROLOGUE"):
        return "prologue"
    if u.startswith("APPENDIX"):
        return "appendix"
    if u.startswith(("NOTES", "INDEX", "BIBLIOGRAPHY", "GLOSSARY", "CATALOGUE", "CATALOG", "ERRATA")):
        return "back_matter"
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


def _following_has_toc_wrap_page(lines: list[str], index: int) -> bool:
    """True when a bare CHAPTER line is followed by a synopsis that ends in a page number."""
    for j in range(index + 1, min(index + 14, len(lines))):
        nxt = lines[j].strip()
        if not nxt:
            continue
        if _CHAPTER_TOC_LINE.match(nxt) or _NAMED_TOC_LINE.match(nxt) or _BOOK_PART_TOC_LINE.match(nxt):
            return False
        if _TOC_STOP.match(nxt):
            return False
        if toc_page_tail(nxt) or is_toc_list_row(nxt):
            return True
    return False


def toc_is_wrap_page_column(entries: list[dict[str, Any]]) -> bool:
    """Abdy-style TOC: chapter heading on its own line, wrap + page column — not Austen one-liners."""
    if len(entries) < 3:
        return False
    wrapped = sum(1 for e in entries if e.get("wrapped"))
    paged = sum(1 for e in entries if e.get("page"))
    return wrapped >= 2 and paged >= 2


# Catalogue / glossary / bibliography are optional. A miss still allows toc_match;
# that tail stays in the previous section. Require every chapter/part/book/preface.
_STRUCTURAL_TOC_KINDS = frozenset({"chapter", "part", "book", "preface", "introduction", "prologue"})


def toc_match_covers_structure(
    entries: list[dict[str, Any]],
    matched: list[dict[str, Any]],
) -> bool:
    """Require every structural TOC entry; unmatched back_matter is allowed."""
    if not entries or not matched:
        return False
    needed = [e for e in entries if e.get("kind") in _STRUCTURAL_TOC_KINDS]
    if not needed:
        needed = list(entries)
    got = {(m.get("index"), m.get("label")) for m in matched}
    return all((e.get("index"), e.get("label")) in got for e in needed)


def is_toc_chapter_block(lines: list[str], index: int) -> bool:
    """True when this CHAPTER line is a contents stub (synopsis + page), not body."""
    if index < 0 or index >= len(lines):
        return False
    stripped = lines[index].strip()
    if not re.match(r"^(?:CHAPTER|CHAP\.?)\s+[IVXLC\d]+\.?\s*$", stripped, re.I):
        return False
    seen = 0
    for j in range(index + 1, min(index + 14, len(lines))):
        nxt = lines[j].strip()
        if not nxt:
            continue
        if re.match(r"^(?:CHAPTER|CHAP\.?)\s+[IVXLC\d]+", nxt, re.I):
            return False
        seen += 1
        if is_toc_list_row(nxt) or toc_page_tail(nxt):
            return True
        if seen >= 8:
            return False
    return False


def _norm_toc_heading(text: str) -> str:
    s = (text or "").lower().replace("\u00a0", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


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

        named = _NAMED_TOC_LINE.match(stripped)
        if named:
            full = strip_toc_page_tail(stripped)
            kind = kind_for_toc_label(full or named.group(1))
            page = toc_page_tail(stripped)
            if (
                entries
                and pending is None
                and any(e.get("kind") == kind for e in entries)
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
            if pending["page"]:
                flush()
            continue

        book_part = _BOOK_PART_TOC_LINE.match(stripped)
        if book_part:
            flush()
            unit = book_part.group(1).upper()
            num = book_part.group(2)
            rest = book_part.group(3).strip()
            label = f"{unit} {num.upper() if not num.isdigit() else num}"
            pending = {
                "label": label,
                "kind": "book" if unit == "BOOK" else "part",
                "title_parts": [strip_toc_page_tail(rest)] if rest and strip_toc_page_tail(rest) else [],
                "page": toc_page_tail(stripped),
            }
            if pending["page"] and not rest:
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


def match_toc_entries_in_body(text: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Locate TOC entries on body heading lines, skipping leftover contents-list rows."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    matched: list[dict[str, Any]] = []
    cursor = -1
    for entry in entries:
        chap = chapter_number_key(str(entry.get("label") or ""))
        needles = [_norm_toc_heading(s) for s in (entry.get("match_strings") or []) if s]
        need_toks = _sig_tokens(str(entry.get("label") or ""))
        found_line: int | None = None
        found_text = ""
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
                    break
                continue
            norm = _norm_toc_heading(raw_line)
            if not norm:
                continue
            if any(n == norm for n in needles if n):
                found_line = line_no
                found_text = raw_line
                break
            if len(need_toks) >= 2 and need_toks <= _sig_tokens(raw_line) and len(raw_line) < 80:
                found_line = line_no
                found_text = raw_line
                break
        if found_line is None:
            continue
        item = dict(entry)
        item["line"] = found_line
        item["text"] = found_text
        matched.append(item)
        cursor = found_line
    return matched
