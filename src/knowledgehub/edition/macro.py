"""Step 1 — macro structure: LLM-assisted chapter/section boundaries (no block parse)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from ..translation.llm_json import parse_json_object
from ..translation.providers import ProviderError, complete_chat
from .profile import detect_family
from .llm_defaults import gemini_available, ref_llm_model
from .ref_schema import REF_PARSER_VERSION
from .toc import is_chapter_heading_line, is_toc_entry_line

STRUCTURE_VERSION = "1"

SECTION_KINDS = frozenset(
    {
        "front_matter",
        "chapter",
        "part",
        "book",
        "preface",
        "introduction",
        "prologue",
        "epilogue",
        "appendix",
        "back_matter",
        "other",
    }
)

HEADING_CANDIDATE = re.compile(
    r"^(?:"
    r"CHAPTER|CHAP\.?|Chapter|BOOK|PART|VOLUME|"
    r"PREFACE|INTRODUCTION|PROLOGUE|EPILOGUE|APPENDIX|"
    r"CHƯƠNG|PHẦN|MỤC|"
    r"Letter|LETTER"
    r")\s+",
    re.I,
)

VI_CHAPTER = re.compile(r"^CHƯƠNG\s+(?:[IVXLC\d]+|[Một Hai Ba][^\n]{0,40})$", re.I)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def line_map(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pos = 0
    for index, part in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
        start = pos
        end = pos + len(part)
        rows.append({"line": index, "start": start, "end": end, "text": part})
        pos = end + 1
    return rows


def scan_heading_candidates(text: str, *, language: str = "en") -> list[dict[str, Any]]:
    lang = (language or "en").lower()[:2]
    rows = line_map(text)
    out: list[dict[str, Any]] = []
    for row in rows:
        stripped = row["text"].strip()
        if not stripped or len(stripped) > 160:
            continue
        if is_toc_entry_line(stripped):
            out.append({**row, "text": stripped, "heuristic": "toc_entry"})
            continue
        if is_chapter_heading_line(stripped) or HEADING_CANDIDATE.match(stripped):
            out.append({**row, "text": stripped, "heuristic": "heading"})
            continue
        if lang == "vi" and VI_CHAPTER.match(stripped):
            out.append({**row, "text": stripped, "heuristic": "heading"})
    return out


def _toc_excerpt(text: str, *, max_chars: int = 3500) -> str:
    rows = line_map(text)
    toc_lines: list[str] = []
    for row in rows[:400]:
        s = row["text"].strip()
        if is_toc_entry_line(s) or s.upper() in {"CONTENTS", "MỤC LỤC", "TABLE OF CONTENTS"}:
            toc_lines.append(s)
            if sum(len(x) + 1 for x in toc_lines) > max_chars:
                break
    if not toc_lines:
        return ""
    return "\n".join(toc_lines[:80])[:max_chars]


def _sections_from_boundaries(
    text: str,
    boundaries: list[dict[str, Any]],
    *,
    language: str,
) -> dict[str, Any]:
    rows = line_map(text)
    line_to_start = {r["line"]: r["start"] for r in rows}
    text_len = len(text)

    ordered = sorted(boundaries, key=lambda b: int(b["start_line"]))
    sections: list[dict[str, Any]] = []
    for index, bound in enumerate(ordered):
        start_line = int(bound["start_line"])
        start_char = int(line_to_start.get(start_line, 0))
        if index + 1 < len(ordered):
            next_line = int(ordered[index + 1]["start_line"])
            end_char = int(line_to_start.get(next_line, text_len)) - 1
        else:
            end_char = text_len - 1
        if end_char < start_char:
            end_char = start_char
        kind = str(bound.get("kind") or "chapter").lower()
        if kind not in SECTION_KINDS:
            kind = "other"
        section_id = f"sec-{len(sections):03d}"
        if kind == "front_matter" and not sections:
            section_id = "sec-000-front"
        slice_text = text[start_char : end_char + 1]
        sections.append(
            {
                "section_id": section_id,
                "kind": kind,
                "title": str(bound.get("title") or f"Section {index + 1}").strip(),
                "subtitle": str(bound.get("subtitle") or "").strip() or None,
                "start_line": start_line,
                "heading_line": bound.get("heading_line", start_line),
                "start_char": start_char,
                "end_char": end_char,
                "word_count": len(re.findall(r"\b[\w'-]+\b", slice_text)),
                "confidence": float(bound.get("confidence") or 0.85),
            }
        )
    return {
        "structure_version": STRUCTURE_VERSION,
        "ref_parser_version": REF_PARSER_VERSION,
        "language": language,
        "section_count": len(sections),
        "sections": sections,
        "created_at": _now(),
    }


def _rule_macro_structure(text: str, candidates: list[dict[str, Any]], *, language: str) -> dict[str, Any]:
    body = [c for c in candidates if c.get("heuristic") == "heading"]
    if not body:
        return _sections_from_boundaries(
            text,
            [{"start_line": 0, "kind": "other", "title": "Full text", "confidence": 0.5}],
            language=language,
        )
    boundaries: list[dict[str, Any]] = []
    first_line = int(body[0]["line"])
    if first_line > 0:
        boundaries.append(
            {"start_line": 0, "kind": "front_matter", "title": "Front matter", "confidence": 0.7}
        )
    for cand in body:
        title = str(cand["text"])
        kind = "chapter"
        upper = title.upper()
        if upper.startswith(("BOOK ", "PART ", "VOLUME ", "PHẦN ")):
            kind = "part" if "PART" in upper or "PHẦN" in upper else "book"
        elif upper.startswith(("PREFACE", "INTRODUCTION", "PROLOGUE")):
            kind = "preface" if "PREFACE" in upper else "introduction"
        boundaries.append(
            {
                "start_line": int(cand["line"]),
                "heading_line": int(cand["line"]),
                "kind": kind,
                "title": title,
                "confidence": 0.72,
            }
        )
    return _sections_from_boundaries(text, boundaries, language=language)


def _llm_macro_prompt(
    *,
    text: str,
    candidates: list[dict[str, Any]],
    language: str,
    family: str,
) -> list[dict[str, str]]:
    head = text[:5000]
    toc = _toc_excerpt(text)
    cand_block = "\n".join(
        f"{c['line']}: [{c.get('heuristic', '?')}] {c['text'][:120]}"
        for c in candidates[:150]
    )
    system = """You segment a public-domain book into reading sections for Knowledge Hub.

Task: pick REAL body section starts (chapters, books, preface in body) — NOT table-of-contents list duplicates.

Rules:
- TOC/list lines (dot leaders, page numbers, short title lists) are NOT body starts — skip them.
- The first body chapter usually appears AFTER the TOC block with its own heading followed by prose.
- Include front_matter from line 0 if imprint/preface/TOC exists before first body chapter.
- Do not rewrite text; only return line numbers already provided in CANDIDATES.

Return ONLY JSON:
{
  "summary_vi": "2-3 câu tiếng Việt",
  "content_kind": "prose|verse|scholastic|mixed|drama",
  "sections": [
    {
      "start_line": 0,
      "heading_line": null,
      "kind": "front_matter|chapter|part|book|preface|introduction|prologue|appendix|back_matter|other",
      "title": "Front matter",
      "subtitle": null,
      "confidence": 0.95
    }
  ]
}"""
    user = f"""Language: {language}
Source family: {family}
Text length: {len(text)} chars

--- HEAD EXCERPT ---
{head}
--- END HEAD ---

--- TOC EXCERPT (may be empty) ---
{toc or "(none detected)"}
--- END TOC ---

--- HEADING CANDIDATES (line: text) ---
{cand_block}
--- END CANDIDATES ---"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_macro_structure(
    text: str,
    *,
    language: str = "en",
    family: str | None = None,
    work: dict[str, Any] | None = None,
    use_llm: bool = True,
    model: str | None = None,
) -> dict[str, Any]:
    """Step 1 — section boundaries on stripped source text (one LLM call, no block parse)."""
    if not text.strip():
        raise ValueError("empty text for macro structure")
    family = family or detect_family(text, work=work, language=language)
    candidates = scan_heading_candidates(text, language=language)

    if use_llm and gemini_available():
        qa_model = model or ref_llm_model()
        try:
            raw = complete_chat(
                _llm_macro_prompt(text=text, candidates=candidates, language=language, family=family),
                model=qa_model,
                temperature=0.1,
                max_tokens=4096,
            )
            parsed = parse_json_object(raw)
            sections_in = parsed.get("sections") or []
            if not isinstance(sections_in, list) or not sections_in:
                raise ProviderError("macro LLM returned no sections")
            doc = _sections_from_boundaries(text, sections_in, language=language)
            doc["mode"] = "llm"
            doc["model"] = qa_model
            doc["summary_vi"] = str(parsed.get("summary_vi") or "")
            doc["content_kind"] = str(parsed.get("content_kind") or "prose")
            doc["candidate_count"] = len(candidates)
            return doc
        except (ProviderError, ValueError, json.JSONDecodeError) as exc:
            doc = _rule_macro_structure(text, candidates, language=language)
            doc["mode"] = "rule_fallback"
            doc["llm_error"] = str(exc)
            doc["candidate_count"] = len(candidates)
            return doc

    doc = _rule_macro_structure(text, candidates, language=language)
    doc["mode"] = "rule"
    doc["candidate_count"] = len(candidates)
    return doc


def section_source_slice(text: str, section: dict[str, Any]) -> str:
    start = int(section.get("start_char") or 0)
    end = int(section.get("end_char") or len(text))
    return text[start : end + 1]
