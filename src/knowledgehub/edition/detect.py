from __future__ import annotations

import re
from typing import Any

from .profile import PG_END, PG_START, edition_overrides
from .spans import EditionSpan

ELECTRONIC_NOTE = re.compile(
    r"NOTE TO THIS ELECTRONIC EDITION\b[\s\S]*?(?=\n(?:CONTENTS|PROLOGUE|PREFACE|INTRODUCTION)\s*\n)",
    re.I,
)
PRODUCED_BY = re.compile(
    r"^\s*Produced by[^\n]*(?:\n(?![A-Z][A-Z].{0,40}$)[^\n]{0,90}){0,8}\n+",
    re.M,
)
TRANSCRIBER = re.compile(
    r"\[\s*Transcriber'?s Note\s*:[\s\S]*?\]",
    re.I,
)
TRANSCRIBER_HEADING = re.compile(
    r"(?m)^[ \t]*Transcriber(?:'?s|s'?)\s+Notes?\s*:?\s*$",
    re.I,
)
PG_END_PLAIN = re.compile(r"(?m)^End of (the )?Project Gutenberg.+$", re.I)
GOOGLE_FRONT = re.compile(
    r"Google\b[\s\S]{200,20000}?books\s*\.\s*google\s*\.\s*com[^\n]*\n+",
    re.I,
)
PUBLISHER_CATALOG = re.compile(
    r"(?m)^(?:WORKS BY|WORKS PUBLISHED(?:\s+BY)?|ALSO BY THE SAME AUTHOR)\s*$",
    re.I,
)
TOC_MARKER = re.compile(r"(?m)^[ \t]*(TABLE OF CONTENTS|CONTENTS)\s*\.?$", re.I)
INDEX_HEADING = re.compile(r"(?m)^[ \t]*(ANALYTICAL INDEX|INDEX)\s*[:.]?\s*$", re.I)
NOTES_HEADING = re.compile(
    r"(?m)^[ \t]*(FOOTNOTES|NOTES(?:\s+TO\s+[A-Z][A-Z0-9 ,.'’:-]{0,60})?)\s*[:.]?\s*$",
    re.I,
)
BODY_HEADING = re.compile(
    r"(?m)^(?:CHAPTER\s+[IVXLC\d]+|BOOK\s+[IVXLC\d]+|VOLUME\s+[IVXLC\d]+|"
    r"PART\s+[IVXLC\d]+|PREFACE|INTRODUCTION|PROLOGUE)\b",
    re.I,
)
CHAP_HEADING = re.compile(
    r"^(?:CHAP(?:TER)?\.?\s+[IVXLC\d]+|BOOK\s+[IVXLC\d]+|VOLUME\s+[IVXLC\d]+|"
    r"PART\s+[IVXLC\d]+|Chapter\s+\S+)",
    re.I,
)
PART_LABEL = re.compile(r"^(?:FIRST|SECOND|THIRD|FOURTH|FIFTH)\s+PART\b", re.I)
RULE_LINE = re.compile(r"^[_=\-\*]{3,}$")
PG_END_LINE = re.compile(r"\*\*\*\s*END OF (THE |THIS )?PROJECT GUTENBERG", re.I)
LIBRARY_STAMP = re.compile(
    r"(?m)^(?:DATE DUE|Stanford University Libraries|Return this book on or before|Music\s*\nLibrary)\b",
    re.I,
)
AOZORA_RUBY = re.compile(r"《[^》]*》")
AOZORA_NOTE = re.compile(r"［＃[^］]*］")
AOZORA_END = re.compile(r"\n(?:本文終わり|底本[：:])")
AOZORA_LEGEND = re.compile(r"【テキスト中に現れる記号について】[\s\S]*?\n-{10,}\n")


def _line_table(text: str) -> list[tuple[int, int, str]]:
    rows: list[tuple[int, int, str]] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        rows.append((pos, pos + len(line), line))
        pos += len(line)
    return rows


def _next_nonempty(rows: list[tuple[int, int, str]], index: int) -> str:
    for _, _, line in rows[index + 1 :]:
        if line.strip():
            return line.strip()
    return ""


def _looks_like_index_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if re.search(r"\d{1,4}$", s):
        return True
    letters = [c for c in s if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.7 and len(s) < 50:
        return True
    return "," in s and len(s) < 80


_HEADING_PAGE_TAIL = re.compile(r"(?:\.{2,}|\s{2,})(?:\d{1,4}|[IVXLCDM]{1,8})$", re.I)


def _heading_key(line: str) -> str:
    s = re.sub(r"\s+", " ", line.strip()).upper()
    return _HEADING_PAGE_TAIL.sub("", s).strip(" .")


def _toc_title_repeats(key: str, seen: set[str]) -> bool:
    """True when a body heading repeats a Contents row (possibly split across lines).

    Prefix match covers Arnold ``NUMBERS;`` ⊆ ``NUMBERS OR THE MAJORITY…``.
    Do not match on the first word alone — ``CHAPTER`` is 7 letters, so that
    branch treated ``CHAPTER IV`` as a repeat of ``CHAPTER I``.
    """
    if not key:
        return False
    if key in seen:
        return True
    compact = re.sub(r"[^A-Z0-9]+", " ", key).strip()
    if len(compact) < 4:
        return False
    from .toc import chapter_number_key

    chap = chapter_number_key(key)
    for prev in seen:
        prev_c = re.sub(r"[^A-Z0-9]+", " ", prev).strip()
        if not prev_c:
            continue
        if compact == prev_c:
            return True
        if len(compact) >= 5 and prev_c.startswith(compact + " "):
            return True
        if chap and chapter_number_key(prev) == chap:
            return True
    return False


def _is_toc_heading(line: str) -> bool:
    s = line.strip()
    return bool(BODY_HEADING.match(s) or CHAP_HEADING.match(s) or PART_LABEL.match(s))


def _looks_like_toc_line(line: str) -> bool:
    """True for contents-list rows, not wrapped prose."""
    s = line.strip()
    if not s or s.startswith("***") or len(s) > 90 or RULE_LINE.match(s):
        return False
    if _is_toc_heading(s):
        return True
    if re.match(r"^\d+\.\s+\S", s):
        return True
    if re.match(r"^[IVXLC]+\.\s+\S", s):
        return True
    if re.search(r"\s+\d{1,4}$", s) and len(s) < 80:
        return True
    if re.search(r"\s{2,}\S", s) and len(s) < 80:
        return True
    if len(s) < 28 and s[0].isupper() and re.match(r"^[A-Za-z][A-Za-z .]*$", s) and s.count(" ") <= 2:
        return True
    letters = [c for c in s if c.isalpha()]
    if letters and len(s) < 60 and sum(1 for c in letters if c.isupper()) / len(letters) > 0.85:
        return True
    return False


def detect_gutenberg_wrappers(text: str) -> list[EditionSpan]:
    spans: list[EditionSpan] = []
    start = PG_START.search(text)
    if start:
        spans.append(
            EditionSpan(0, start.end(), "wrapper", "drop", 0.99, "Project Gutenberg header")
        )
    ends = [m.start() for m in (PG_END.search(text), PG_END_PLAIN.search(text)) if m]
    if ends:
        spans.append(
            EditionSpan(min(ends), len(text), "wrapper", "drop", 0.99, "Project Gutenberg license footer")
        )
    return spans


def detect_front_apparatus(text: str, *, family: str) -> list[EditionSpan]:
    if family not in {"gutenberg", "scholastic"}:
        return []
    spans: list[EditionSpan] = []
    for match in TRANSCRIBER.finditer(text):
        spans.append(
            EditionSpan(
                match.start(),
                match.end(),
                "transcriber",
                "drop",
                0.95,
                "Transcriber note",
            )
        )
    for match in TRANSCRIBER_HEADING.finditer(text):
        if match.start() < int(len(text) * 0.7):
            continue
        end = len(text)
        pg = PG_END.search(text, match.start())
        if pg:
            end = pg.start()
        spans.append(
            EditionSpan(
                match.start(),
                end,
                "transcriber",
                "drop",
                0.92,
                "Transcriber notes at end",
            )
        )
    note = ELECTRONIC_NOTE.search(text)
    if note and note.start() < max(8000, int(len(text) * 0.08)):
        spans.append(
            EditionSpan(
                note.start(),
                note.end(),
                "electronic_note",
                "drop",
                0.96,
                "Electronic-edition note",
            )
        )
    produced = PRODUCED_BY.search(text)
    if produced and produced.start() < 2500:
        spans.append(
            EditionSpan(
                produced.start(),
                produced.end(),
                "produced_by",
                "drop",
                0.9,
                "Produced-by credit",
            )
        )
    return spans


def _body_open_start(rows: list[tuple[int, int, str]], index: int) -> int:
    """Keep a short CHAPTER/INTRODUCTION cluster immediately before body prose."""
    start = rows[index][0]
    headings = 0
    for j in range(index - 1, -1, -1):
        a, _, raw = rows[j]
        s = raw.strip()
        if not s or RULE_LINE.match(s):
            continue
        if BODY_HEADING.match(s) and start - a < 400 and headings < 3:
            start = a
            headings += 1
            continue
        break
    return start


def detect_toc(text: str, *, family: str) -> list[EditionSpan]:
    if family not in {"gutenberg", "scholastic"}:
        return []
    marker = TOC_MARKER.search(text)
    if not marker or marker.start() > max(16000, int(len(text) * 0.08)):
        return []
    rows = _line_table(text)
    start_i = next((i for i, (a, _, _) in enumerate(rows) if a >= marker.start()), None)
    if start_i is None:
        return []
    toc_lines = 0
    cut_at: int | None = None
    seen: set[str] = set()
    window = max(28000, int(len(text) * 0.08))
    for i, (a, _b, raw) in enumerate(rows[start_i + 1 :], start=start_i + 1):
        s = raw.strip()
        if not s or RULE_LINE.match(s):
            continue
        if PG_END_LINE.search(s) or a - marker.start() > window:
            break
        key = _heading_key(s)
        if toc_lines >= 3 and _toc_title_repeats(key, seen):
            cut_at = a
            break
        if _looks_like_toc_line(s):
            toc_lines += 1
            seen.add(key)
            continue
        if toc_lines >= 6 and len(s) >= 55:
            cut_at = _body_open_start(rows, i)
            break
        if toc_lines < 3 and len(s) < 90:
            continue
        seen.add(key)
    if cut_at is None or toc_lines < 4 or cut_at <= marker.start():
        return [
            EditionSpan(
                marker.start(),
                marker.end(),
                "toc",
                "keep",
                0.4,
                "Possible contents heading; not enough TOC evidence to drop",
            )
        ]
    confidence = 0.92 if toc_lines >= 12 else 0.86
    return [
        EditionSpan(marker.start(), cut_at, "toc", "drop", confidence, f"Front contents list ({toc_lines} entries)")
    ]


def detect_tail_index(text: str) -> list[EditionSpan]:
    spans: list[EditionSpan] = []
    cutoff = int(len(text) * 0.4)
    for match in INDEX_HEADING.finditer(text):
        if match.start() < cutoff:
            continue
        rows = _line_table(text)
        start_i = next((i for i, (a, _, _) in enumerate(rows) if a >= match.start()), None)
        if start_i is None:
            continue
        end = len(text)
        index_like = 0
        for i, (a, b, raw) in enumerate(rows[start_i + 1 :], start=start_i + 1):
            s = raw.strip()
            if not s:
                continue
            if (
                NOTES_HEADING.match(s)
                or TRANSCRIBER_HEADING.match(s)
                or PG_END.search(s)
                or PG_END_PLAIN.match(s)
            ):
                end = a
                break
            if BODY_HEADING.match(s) and a > match.start() + 400:
                end = a
                break
            if _looks_like_index_line(s):
                index_like += 1
            elif len(s) > 110:
                # long prose soon after INDEX — probably not a back-of-book index
                if index_like < 8:
                    end = match.start()
                else:
                    end = a
                break
        if end <= match.start() or index_like < 8:
            spans.append(
                EditionSpan(
                    match.start(),
                    match.end(),
                    "index",
                    "keep",
                    0.35,
                    "INDEX heading without index-like run; kept",
                )
            )
            continue
        spans.append(
            EditionSpan(
                match.start(),
                end,
                "index",
                "drop",
                0.93 if index_like >= 20 else 0.87,
                f"Back-of-book index ({index_like} entries)",
            )
        )
    return spans


def detect_notes(text: str) -> list[EditionSpan]:
    spans: list[EditionSpan] = []
    for match in NOTES_HEADING.finditer(text):
        titled = bool(re.match(r"(?i)NOTES\s+TO\s+", match.group()))
        if match.start() < int(len(text) * 0.4) and not titled:
            continue
        rows = _line_table(text)
        start_i = next((i for i, (a, _, _) in enumerate(rows) if a >= match.start()), None)
        if start_i is None:
            continue
        end = len(text)
        for a, _, raw in rows[start_i + 1 :]:
            s = raw.strip()
            if not s:
                continue
            if (
                INDEX_HEADING.match(s)
                or TRANSCRIBER_HEADING.match(s)
                or PG_END.search(s)
                or PG_END_PLAIN.match(s)
            ):
                end = a
                break
        spans.append(
            EditionSpan(
                match.start(),
                end,
                "notes",
                "keep",
                0.9,
                "Author/editor notes — keep in edition (do not treat as paper index)",
            )
        )
    return spans


def detect_aozora(text: str) -> list[EditionSpan]:
    spans: list[EditionSpan] = []
    legend = AOZORA_LEGEND.search(text)
    if legend:
        spans.append(EditionSpan(0 if legend.start() < 80 else legend.start(), legend.end(), "wrapper", "drop", 0.95, "Aozora symbol legend"))
    end = AOZORA_END.search(text)
    if end:
        spans.append(EditionSpan(end.start(), len(text), "wrapper", "drop", 0.95, "Aozora colophon"))
    return spans


def detect_google_scan(text: str, *, family: str) -> list[EditionSpan]:
    if family != "archive_scan":
        return []
    sample = text[: min(len(text), 25000)]
    match = GOOGLE_FRONT.search(sample)
    if not match or match.start() > 400:
        return []
    return [
        EditionSpan(
            0,
            match.end(),
            "scan_boilerplate",
            "drop",
            0.94,
            "Google Books scan boilerplate",
        )
    ]


def detect_publisher_ads(text: str, *, family: str) -> list[EditionSpan]:
    if family not in {"gutenberg", "scholastic"}:
        return []
    cutoff = int(len(text) * 0.75)
    match = PUBLISHER_CATALOG.search(text)
    if not match or match.start() < cutoff:
        return []
    end = len(text)
    pg = PG_END.search(text, match.start())
    if pg:
        end = pg.start()
    trans = TRANSCRIBER_HEADING.search(text, match.start())
    if trans:
        end = min(end, trans.start())
    if end - match.start() < 250:
        return []
    return [
        EditionSpan(
            match.start(),
            end,
            "ads",
            "drop",
            0.9,
            "Publisher catalog at end of volume",
        )
    ]


def detect_library_stamp(text: str, *, family: str) -> list[EditionSpan]:
    if family != "archive_scan":
        return []
    match = LIBRARY_STAMP.search(text)
    if not match or match.start() < int(len(text) * 0.7):
        return []
    return [
        EditionSpan(
            match.start(),
            len(text),
            "library_stamp",
            "drop",
            0.9,
            "Library checkout / shelf stamp at end of scan",
        )
    ]


def collect_spans(
    text: str,
    *,
    family: str,
    work: dict[str, Any] | None = None,
    preserve_toc: bool = False,
) -> list[EditionSpan]:
    overrides = edition_overrides(work)
    spans: list[EditionSpan] = []
    if family in {"gutenberg", "scholastic"}:
        spans.extend(detect_gutenberg_wrappers(text))
        spans.extend(detect_front_apparatus(text, family=family))
        if not preserve_toc:
            spans.extend(detect_toc(text, family=family))
    if family == "aozora":
        spans.extend(detect_aozora(text))
    spans.extend(detect_notes(text))
    if overrides.get("keep_index"):
        pass
    else:
        spans.extend(detect_tail_index(text))
    spans.extend(detect_publisher_ads(text, family=family))
    spans.extend(detect_google_scan(text, family=family))
    spans.extend(detect_library_stamp(text, family=family))
    spans.sort(key=lambda s: (s.start, s.end, s.kind))
    return spans
