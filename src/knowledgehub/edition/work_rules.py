"""Book-specific matchers (not a CMS rules engine). Run after parse, before HITL quotes."""

from __future__ import annotations

import re
from typing import Any

from .inline_spans import annotate_blocks
from .figures import FIGURE_MARKER_RE, FIGURE_OPEN_RE

SIDENOTE_RE = re.compile(r"\[Sidenote:\s*(.*?)\]", re.I | re.S)
OBJECT_REPLACEMENT = "\ufffc"
PERSON_ITEM = re.compile(
    r"(\d+)\.\s+"
    r"([A-Z][A-ZÀ-ÿÆŒ .''-]{1,80}"
    r"(?:,\s*(?:d\.\s*)?\d{3,4}(?:\s*[-–—]\s*(?:\d{2,4}|[.]{2,}))?)?)"
    r"\.?",
)
GENEALOGY_START = re.compile(r"THE BACH FAMILY|Hilgenfeldt|Genealogy", re.I)
CHAPTER_HEAD = re.compile(r"^(?:CHAPTER|BOOK|PART|VOLUME)\b", re.I)
SONS_OF = re.compile(r"^_?(Sons|Daughters|Children) of\b", re.I)


def apply_work_rules(
    blocks: list[dict[str, Any]],
    *,
    work_id: str | None = None,
    family: str = "gutenberg",
) -> list[dict[str, Any]]:
    """Deterministic matchers. Re-annotates spans when text is rewritten."""
    wid = str(work_id or "")
    out = [dict(block) for block in blocks]
    out = apply_pg_sidenote(out)
    out = apply_pg_illustration(out)
    if _uses_synopsis(wid, family):
        out = apply_chapter_synopsis(out)
    if _uses_genealogy(wid):
        out = apply_bach_genealogy(out)
    annotated, _profile = annotate_blocks(out)
    return annotated


def _uses_synopsis(work_id: str, family: str) -> bool:
    if work_id.startswith("bach--"):
        return True
    if family != "gutenberg":
        return False
    # Master Musicians series — not any id that merely contains "master".
    return "master_musician" in work_id or "master--" in work_id


def _uses_genealogy(work_id: str) -> bool:
    return work_id == "bach--abdy_williams" or work_id.startswith("bach--abdy")


def apply_pg_sidenote(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in blocks:
        text = str(block.get("text") or "")
        if not SIDENOTE_RE.search(text):
            out.append(block)
            continue
        remainder = text
        for match in SIDENOTE_RE.finditer(text):
            aside = match.group(1).strip()
            if aside:
                out.append(
                    {
                        "type": "paragraph",
                        "role": "aside",
                        "hidden": True,
                        "hidden_reason": "sidenote",
                        "text": aside,
                    }
                )
            remainder = SIDENOTE_RE.sub("", remainder, count=1)
        remainder = re.sub(r"[ \t]{2,}", " ", remainder).strip()
        if remainder:
            row = dict(block)
            row["text"] = remainder
            row.pop("spans", None)
            out.append(row)
    return out


def _figure_unclosed(text: str) -> bool:
    last = None
    for match in FIGURE_OPEN_RE.finditer(text or ""):
        last = match
    if last is None:
        return False
    return "]" not in (text or "")[last.end() :]


def _split_figure_block(block: dict[str, Any], text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    remainder = text
    for match in FIGURE_MARKER_RE.finditer(text):
        kind = (match.group(1) or "Illustration").strip()
        caption = (match.group(2) or "").strip()
        caption = caption.replace(OBJECT_REPLACEMENT, "").strip()
        if not caption:
            caption = "Music" if kind.lower() == "music" else "Illustration"
        out.append({"type": "paragraph", "role": "figure", "text": caption})
        remainder = FIGURE_MARKER_RE.sub("", remainder, count=1)
    remainder = re.sub(r"[ \t]{2,}", " ", remainder).replace(OBJECT_REPLACEMENT, "").strip()
    if remainder:
        row = dict(block)
        row["text"] = remainder
        row.pop("spans", None)
        if row.get("role") == "figure":
            row.pop("role", None)
        out.append(row)
    return out


def apply_pg_illustration(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        text = str(block.get("text") or "")
        if OBJECT_REPLACEMENT in text and not FIGURE_OPEN_RE.search(text):
            row = dict(block)
            row["role"] = "figure"
            cleaned = text.replace(OBJECT_REPLACEMENT, "").strip()
            row["text"] = cleaned or OBJECT_REPLACEMENT
            row.pop("spans", None)
            out.append(row)
            i += 1
            continue
        if _figure_unclosed(text):
            parts = [text]
            j = i + 1
            while j < len(blocks) and _figure_unclosed(" ".join(parts)) and (j - i) < 40:
                parts.append(str(blocks[j].get("text") or ""))
                j += 1
            joined = " ".join(parts)
            if FIGURE_MARKER_RE.search(joined):
                out.extend(_split_figure_block(block, joined))
                i = j
                continue
        if FIGURE_MARKER_RE.search(text):
            out.extend(_split_figure_block(block, text))
            i += 1
            continue
        out.append(block)
        i += 1
    return out


def apply_chapter_synopsis(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        block = dict(blocks[i])
        out.append(block)
        if _is_chapter_heading(block) and i + 1 < len(blocks):
            nxt = dict(blocks[i + 1])
            if _looks_like_synopsis(str(nxt.get("text") or "")):
                nxt["type"] = "paragraph"
                nxt["role"] = "synopsis"
                out.append(nxt)
                i += 2
                continue
        i += 1
    return out


def _is_chapter_heading(block: dict[str, Any]) -> bool:
    if block.get("type") != "heading":
        return False
    text = str(block.get("text") or "").strip()
    return bool(CHAPTER_HEAD.match(text)) or int(block.get("level") or 1) == 1


def _looks_like_synopsis(text: str) -> bool:
    body = re.sub(r"\s+", " ", text).strip()
    if len(body) < 40 or len(body) > 900:
        return False
    dashes = body.count("—") + body.count("–") + body.count("--")
    if dashes < 3:
        return False
    return dashes / max(body.count(" "), 1) >= 0.08 or dashes >= 5


def apply_bach_genealogy(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    in_region = False
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        text = str(block.get("text") or "")
        if GENEALOGY_START.search(text) or (block.get("type") == "heading" and "GENEALOGY" in text.upper()):
            in_region = True
        if in_region and _is_chapter_heading(block) and not GENEALOGY_START.search(text):
            in_region = False
        if in_region and _is_genealogy_payload(text):
            out.extend(_split_genealogy_block(block))
            i += 1
            continue
        if in_region and SONS_OF.match(text.strip().strip("_")):
            row = dict(block)
            row["type"] = "paragraph"
            row["role"] = "list_caption"
            row.pop("level", None)
            out.append(row)
            i += 1
            continue
        out.append(dict(block))
        i += 1
    return out


def _is_genealogy_payload(text: str) -> bool:
    return len(PERSON_ITEM.findall(text)) >= 1 and (
        re.search(r"\d{3,4}\s*[-–—]", text) or text.count(".") >= 1
    )


def _split_genealogy_block(block: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(block.get("text") or "")
    items = list(PERSON_ITEM.finditer(text))
    if not items:
        return [dict(block)]
    out: list[dict[str, Any]] = []
    leftover_head = text[: items[0].start()].strip()
    if leftover_head and not re.fullmatch(r"\d+\.?", leftover_head):
        head = dict(block)
        head["text"] = leftover_head
        head.pop("spans", None)
        out.append(head)
    for match in items:
        number, name = match.group(1), match.group(2).strip().rstrip(".")
        out.append(
            {
                "type": "list_item",
                "role": "genealogy",
                "text": f"{number}. {name}.",
            }
        )
    tail = text[items[-1].end() :].strip()
    if tail and not re.fullmatch(r"\d+\.?", tail):
        out.append({"type": "paragraph", "text": tail})
    return out
