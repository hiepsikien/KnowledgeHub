"""Vietnamese TOC labels for translation chapters."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ..settings import resolve_models
from .llm_json import parse_json_object
from .providers import ProviderError, complete_prompt

_ROMAN = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
    "xiii": 13,
    "xiv": 14,
    "xv": 15,
    "xvi": 16,
    "xvii": 17,
    "xviii": 18,
    "xix": 19,
    "xx": 20,
}
_NAMED_VI = {
    "preface": "Lời nói đầu",
    "foreword": "Lời tựa",
    "introduction": "Lời dẫn",
    "prologue": "Mở đầu",
    "epilogue": "Lời kết",
    "appendix": "Phụ lục",
    "bibliography": "Thư mục",
    "glossary": "Bảng chú giải",
    "contents": "Mục lục",
    "index": "Chỉ mục",
}
_CHAPTER_HEAD = re.compile(
    r"^(?:chapter|chap\.?|ch\.?)?\s*([ivxlc]+|\d+)\.?\s*$",
    re.I,
)
_COMPACT_CHAPTER = re.compile(r"^(?:chapter|chap)?([ivxlc]+|\d+)$", re.I)

_TITLE_SYSTEM = """You translate table-of-contents headings into Vietnamese for Knowledge Hub.

Rules:
- Return JSON only: {"titles": ["...", ...]} with the same order and length as the input.
- "Chapter I", "CHAPTER I", "Chapter 1", or "I" → "Chương 1". Use Arabic numerals, never Roman, never the English word Chapter.
- Preface → Lời nói đầu. Bibliography → Thư mục. Glossary → Bảng chú giải.
- "Catalogue of …" → "Mục lục …" in Vietnamese.
- Short TOC labels only. No quotes. No extra numbering.
"""


def english_heading(segment: dict[str, Any]) -> str:
    titled = str(segment.get("ref_title") or segment.get("title") or "").strip()
    if titled:
        return titled
    raw = str(segment.get("chapter") or "").strip()
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw)
    spaced = re.sub(r"([A-Za-z])(\d)", r"\1 \2", spaced)
    return spaced or raw


def _chapter_number(text: str) -> int | None:
    stripped = (text or "").strip()
    compact = re.sub(r"[^A-Za-z0-9]", "", stripped)
    match = _CHAPTER_HEAD.fullmatch(stripped) or _COMPACT_CHAPTER.fullmatch(compact)
    if not match:
        return None
    token = match.group(1).lower()
    if token.isdigit():
        return int(token)
    return _ROMAN.get(token)


def fallback_title_vi(text: str) -> str:
    stripped = (text or "").strip()
    number = _chapter_number(stripped)
    if number is not None:
        return f"Chương {number}"
    compact = re.sub(r"[^A-Za-z0-9]", "", stripped).lower()
    if compact in _NAMED_VI:
        return _NAMED_VI[compact]
    lower = stripped.lower()
    if lower.startswith("catalogue of ") or lower.startswith("catalog of "):
        rest = stripped.split(" ", 2)[-1].strip()
        return f"Mục lục {rest}" if rest else "Mục lục"
    if compact.startswith("catalogue") or compact.startswith("catalog"):
        return "Mục lục"
    return stripped or "Chương"


def translate_chapter_titles(
    titles: list[str],
    *,
    model: str | None = None,
    use_llm: bool | None = None,
) -> list[str]:
    fallbacks = [fallback_title_vi(title) for title in titles]
    if not titles:
        return []
    if use_llm is None:
        use_llm = not os.environ.get("PYTEST_CURRENT_TEST")
    if not use_llm:
        return fallbacks
    numbered = "\n".join(f"{index + 1}. {title}" for index, title in enumerate(titles))
    try:
        raw = complete_prompt(
            f"Headings:\n{numbered}",
            model=model or resolve_models()["draft"],
            system=_TITLE_SYSTEM,
            temperature=0.1,
            max_tokens=2048,
        )
        parsed = parse_json_object(raw)
        rows = parsed.get("titles")
        if not isinstance(rows, list) or len(rows) != len(titles):
            return fallbacks
        out: list[str] = []
        for index, item in enumerate(rows):
            label = str(item or "").strip()
            out.append(label or fallbacks[index])
        return out
    except (ProviderError, ValueError, TypeError, KeyError):
        return fallbacks


def display_title_vi(segment: dict[str, Any]) -> str:
    stored = str(segment.get("title_vi") or "").strip()
    if stored:
        return stored
    return fallback_title_vi(english_heading(segment))


def merge_segment_title_vi(path: Path, title_vi: str) -> None:
    """Write only title_vi onto the latest file bytes — never a stale in-memory segment."""
    label = str(title_vi or "").strip()
    if not label or not path.is_file():
        return
    segment = json.loads(path.read_text(encoding="utf-8"))
    if str(segment.get("title_vi") or "").strip() == label:
        return
    segment["title_vi"] = label
    path.write_text(json.dumps(segment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
