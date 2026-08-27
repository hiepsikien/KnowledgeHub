from __future__ import annotations

import re
from typing import Any

HEADER_END = re.compile(
    r"\*\*\*\s*START OF (THE |THIS )?PROJECT GUTENBERG EBOOK[^*\n]*\*\*\*",
    re.I,
)
FOOTER_START = re.compile(
    r"\*\*\*\s*END OF (THE |THIS )?PROJECT GUTENBERG EBOOK",
    re.I,
)
ELECTRONIC_NOTE = re.compile(
    r"NOTE TO THIS ELECTRONIC EDITION\b[\s\S]*?(?=\n(?:CONTENTS|PROLOGUE|PREFACE|INTRODUCTION)\s*\n)",
    re.I,
)
PRODUCED_BY = re.compile(
    r"^\s*Produced by[^\n]*(?:\n(?![A-Z][A-Z].{0,40}$)[^\n]{0,90}){0,8}\n+",
    re.M,
)
TOC_END = re.compile(
    r"(?m)^(PROLOGUE|PREFACE|INTRODUCTION|CHAPTER\s+[IVXLC1]|BOOK\s+[IVXLC1]|PART\s+[IVXLC1]|FIRST PART)\b"
)
TAIL_INDEX = (
    r"\nANALYTICAL INDEX\b",
    r"\nINDEX\b",
    r"\nNOTES\b",
    r"\nFOOTNOTES\b",
)
AOZORA_RUBY = re.compile(r"《[^》]*》")
AOZORA_NOTE = re.compile(r"［＃[^］]*］")
AOZORA_END = re.compile(r"\n(?:本文終わり|底本[：:])")
AOZORA_LEGEND = re.compile(
    r"【テキスト中に現れる記号について】[\s\S]*?\n-{10,}\n",
)
HARD_STRUCTURAL = re.compile(
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
SOFT_STRUCTURAL = re.compile(
    r"^(?:Objection\s+\d|Obj\.\s+\d|Reply Obj|_On the contrary|_I answer that)",
    re.I,
)
ORDINAL_WRAP = 55
CJK_LANG = {"ja", "zh", "ko"}


def strip_gutenberg(text: str) -> tuple[str, bool]:
    start = HEADER_END.search(text)
    hit = bool(start)
    if start:
        text = text[start.end() :]
    end = FOOTER_START.search(text)
    hit = hit or bool(end)
    if end:
        text = text[: end.start()]
    return text.strip(), hit


def strip_tail_index(text: str) -> tuple[str, bool]:
    dropped = False
    for marker in TAIL_INDEX:
        m = re.search(marker, text, re.I)
        if m and m.start() > len(text) * 0.5:
            text = text[: m.start()]
            dropped = True
            break
    return text.strip(), dropped


def strip_front_contents(text: str) -> tuple[str, bool]:
    m = re.search(r"(?m)^CONTENTS\s*$", text)
    if not m or m.start() > max(12000, int(len(text) * 0.12)):
        return text, False
    rest = text[m.end() :]
    chosen = None
    for end in TOC_END.finditer(rest):
        after = [ln.strip() for ln in rest[end.end() :].splitlines() if ln.strip()]
        nxt = after[0] if after else ""
        if len(nxt) >= 60:
            chosen = end
            break
    if not chosen:
        return text, False
    block = rest[: chosen.start()]
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 4:
        return text, False
    short = sum(1 for ln in lines if len(ln) < 80)
    if short / len(lines) < 0.7:
        return text, False
    cleaned = (text[: m.start()] + "\n\n" + rest[chosen.start() :]).strip()
    return cleaned, True


def strip_electronic_apparatus(text: str) -> tuple[str, dict[str, bool]]:
    flags = {"dropped_electronic_note": False, "dropped_produced_by": False, "dropped_contents": False}
    note = ELECTRONIC_NOTE.search(text)
    if note and note.start() < max(8000, len(text) * 0.08):
        text = text[: note.start()] + text[note.end() :]
        flags["dropped_electronic_note"] = True
    produced = PRODUCED_BY.search(text)
    if produced and produced.start() < 400:
        text = text[: produced.start()] + text[produced.end() :]
        flags["dropped_produced_by"] = True
    text, flags["dropped_contents"] = strip_front_contents(text)
    return text.strip(), flags


def strip_aozora(text: str) -> tuple[str, bool]:
    original = text
    legend = AOZORA_LEGEND.search(text)
    if legend:
        text = text[legend.end() :]
    else:
        cut = re.search(r"\n-{10,}\n", text)
        if cut and cut.start() < min(4000, max(1, len(text) // 3)):
            text = text[cut.end() :]
    text = text.replace("｜", "")
    text = AOZORA_RUBY.sub("", text)
    text = AOZORA_NOTE.sub("", text)
    end = AOZORA_END.search(text)
    if end:
        text = text[: end.start()]
    cleaned = text.strip()
    return cleaned, cleaned != original.strip()


def is_all_caps_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 8 or len(line) >= 90:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.85


def is_hard_structural(line: str) -> bool:
    return bool(HARD_STRUCTURAL.match(line)) or is_all_caps_heading(line)


def is_soft_structural(line: str) -> bool:
    return bool(SOFT_STRUCTURAL.match(line))


def looks_like_wrap(line: str) -> bool:
    if len(line) < ORDINAL_WRAP:
        return False
    return not is_hard_structural(line)


def _glue(paragraph: str, last_line: str, nxt: str) -> tuple[str, str]:
    if last_line.endswith("-") and nxt[:1].islower():
        return paragraph[: -len(last_line)] + last_line[:-1] + nxt, nxt
    return paragraph + " " + nxt, nxt


def reflow_block(lines: list[str]) -> tuple[str, bool]:
    if not lines:
        return "", False
    out = lines[0]
    prev = lines[0]
    joined = False
    for line in lines[1:]:
        if looks_like_wrap(prev) and not is_hard_structural(line) and not is_soft_structural(line):
            out, prev = _glue(out, prev, line)
            joined = True
        else:
            out += "\n" + line
            prev = line
    return out, joined


def unwrap_hard_wrap(text: str) -> tuple[str, bool]:
    """Join Gutenberg ~70-char wraps; keep headings and blank-line paragraphs."""
    blocks: list[str] = []
    acc: list[str] = []
    joined = False

    def flush() -> None:
        nonlocal joined
        if not acc:
            return
        block, hit = reflow_block(acc)
        blocks.append(block)
        joined = joined or hit
        acc.clear()

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw.strip():
            flush()
            continue
        line = raw.strip()
        if is_hard_structural(line):
            flush()
            blocks.append(line)
            continue
        if is_soft_structural(line):
            flush()
        acc.append(line)
    flush()
    return "\n\n".join(blocks).strip(), joined


def normalize_manuscript(text: str, *, language: str = "en") -> tuple[str, dict[str, Any]]:
    """Edition text for consumers. Does not rewrite the source file."""
    source_chars = len(text)
    gutenberg = False
    aozora = False
    tail = False
    apparatus = {"dropped_electronic_note": False, "dropped_produced_by": False, "dropped_contents": False}

    body, gutenberg = strip_gutenberg(text)
    if (language or "").lower().startswith("ja"):
        body, aozora = strip_aozora(body)
    body, apparatus = strip_electronic_apparatus(body)
    body, tail = strip_tail_index(body)
    unwrapped = False
    lang = (language or "en").lower()[:2]
    if lang not in CJK_LANG:
        body, unwrapped = unwrap_hard_wrap(body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if not body:
        raise ValueError("normalize_manuscript produced empty text")
    return body, {
        "source_chars": source_chars,
        "published_chars": len(body),
        "gutenberg": gutenberg,
        "aozora": aozora,
        "dropped_electronic_note": apparatus["dropped_electronic_note"],
        "dropped_produced_by": apparatus["dropped_produced_by"],
        "dropped_contents": apparatus["dropped_contents"],
        "dropped_tail_index": tail,
        "unwrapped": unwrapped,
    }
