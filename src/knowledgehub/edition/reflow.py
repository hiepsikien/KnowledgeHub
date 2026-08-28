from __future__ import annotations

import re

ORDINAL_WRAP = 55
CJK_LANG = {"ja", "zh", "ko"}

HARD_GUTENBERG = re.compile(
    r"^(?:"
    r"[_\-=]{3,}|"
    r"(?:CHAPTER|BOOK|PART|PREFACE|INTRODUCTION|CONTENTS|DEDICATION|APPENDIX|PROLOGUE)\b|"
    r"VOLUME\b"
    r")",
    re.I,
)
HARD_SCHOLASTIC = re.compile(
    r"^(?:"
    r"[_\-=]{3,}|"
    r"QUESTION\s+\d|"
    r"(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|ELEVENTH|TWELFTH)\s+ARTICLE\b|"
    r"(?:CHAPTER|BOOK|PART|PROLOGUE|PREFACE|INTRODUCTION|CONTENTS|DEDICATION|APPENDIX)\b|"
    r"TREATISE\b|"
    r"SUMMA THEOLOGICA|"
    r"\([^)]*Articles?\)"
    r")",
    re.I,
)
SOFT_SCHOLASTIC = re.compile(
    r"^(?:Objection\s+\d|Obj\.\s+\d|Reply Obj|_On the contrary|_I answer that)",
    re.I,
)


def is_all_caps_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 8 or len(line) >= 90:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.85


def is_hard_structural(line: str, *, family: str = "gutenberg") -> bool:
    pat = HARD_SCHOLASTIC if family == "scholastic" else HARD_GUTENBERG
    return bool(pat.match(line)) or is_all_caps_heading(line)


def is_soft_structural(line: str, *, family: str = "gutenberg") -> bool:
    if family != "scholastic":
        return False
    return bool(SOFT_SCHOLASTIC.match(line))


def looks_like_wrap(line: str, *, family: str) -> bool:
    if len(line) < ORDINAL_WRAP:
        return False
    return not is_hard_structural(line, family=family)


def _glue(paragraph: str, last_line: str, nxt: str) -> tuple[str, str]:
    if last_line.endswith("-") and nxt[:1].islower():
        return paragraph[: -len(last_line)] + last_line[:-1] + nxt, nxt
    return paragraph + " " + nxt, nxt


def reflow_block(lines: list[str], *, family: str) -> tuple[str, bool]:
    if not lines:
        return "", False
    out = lines[0]
    prev = lines[0]
    joined = False
    for line in lines[1:]:
        if (
            looks_like_wrap(prev, family=family)
            and not is_hard_structural(line, family=family)
            and not is_soft_structural(line, family=family)
        ):
            out, prev = _glue(out, prev, line)
            joined = True
        else:
            out += "\n" + line
            prev = line
    return out, joined


def unwrap_hard_wrap(text: str, *, family: str = "gutenberg", language: str = "en") -> tuple[str, bool]:
    """Join ~70-char wraps; keep headings. Skip CJK and messy OCR scans."""
    if family == "archive_scan" or (language or "en").lower()[:2] in CJK_LANG:
        return text.strip(), False
    blocks: list[str] = []
    acc: list[str] = []
    joined = False

    def flush() -> None:
        nonlocal joined
        if not acc:
            return
        block, hit = reflow_block(acc, family=family)
        blocks.append(block)
        joined = joined or hit
        acc.clear()

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw.strip():
            flush()
            continue
        line = raw.strip()
        if is_hard_structural(line, family=family):
            flush()
            blocks.append(line)
            continue
        if is_soft_structural(line, family=family):
            flush()
        acc.append(line)
    flush()
    return "\n\n".join(blocks).strip(), joined
