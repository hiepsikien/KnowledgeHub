from __future__ import annotations

import re

PAGE_SEPARATOR = re.compile(r"\n- - -[^\n]*\n")
CHAPTER_HEADING = re.compile(r"(?m)^CHAPTER ([IVXLC]+)\.?\s*$")
INTRODUCTORY_NOTE = re.compile(r"(?m)^INTRODUCTORY NOTE\s*$")
INDEX_HEADING = re.compile(r"(?m)^INDEX\s*$")


def _english_block(block: str) -> bool:
    en = len(re.findall(r"\b(the|and|of|to|which|that|nation|Dutch)\b", block, re.I))
    lat = len(re.findall(r"\b(vero|autem|quod|quae|hinc|igitur|gentium)\b", block, re.I))
    if "CHAPTER" in block[:120]:
        return True
    return en > lat


def extract_english_treatise(text: str) -> tuple[str, dict[str, int]]:
    """Keep Magoffin English chapters from the bilingual Carnegie/Gutenberg edition."""
    start = CHAPTER_HEADING.search(text)
    if not start:
        raise ValueError("Could not find CHAPTER I in Grotius text")
    idx = INDEX_HEADING.search(text, start.start())
    treatise = text[start.start() : idx.start() if idx else len(text)]
    blocks = PAGE_SEPARATOR.split(treatise)
    english: list[str] = []
    latin_skipped = 0
    for i, block in enumerate(blocks):
        block = block.strip()
        if not block:
            continue
        if i % 2 == 0 and _english_block(block):
            english.append(block)
        elif i % 2 == 1 or not _english_block(block):
            if not _english_block(block):
                latin_skipped += 1
            else:
                english.append(block)
    body = "\n\n".join(english).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    if not body:
        raise ValueError("English treatise extraction produced empty text")
    words = len(re.findall(r"\b[\w'-]+\b", body))
    chapters = len(CHAPTER_HEADING.findall(body))
    return body, {
        "english_blocks": len(english),
        "latin_blocks_skipped": latin_skipped,
        "words": words,
        "chapters": chapters,
        "chars": len(body),
    }


def split_chapters(text: str) -> list[tuple[str, str]]:
    """Return [(chapter_num, body_text), ...] for CHAPTER I..N."""
    matches = list(CHAPTER_HEADING.finditer(text))
    if not matches:
        raise ValueError("No CHAPTER headings found")
    out: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        num = match.group(1)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        out.append((num, chunk))
    return out
