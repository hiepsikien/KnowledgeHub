"""Smart LLM QA for Step 1 macro structure — boundary excerpts only, not full book."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from ..translation.llm_json import parse_json_object
from ..translation.providers import ProviderError, complete_chat
from .llm_defaults import gemini_available, ref_llm_model
from .macro import _toc_excerpt, scan_heading_candidates, section_source_slice
from .toc import is_all_caps_body_section_line, is_all_caps_section_line, is_body_heading_line, is_chapter_heading_line, is_toc_entry_line

CONTENTS_HEAD = re.compile(r"(?m)^[ \t]*(TABLE OF CONTENTS|CONTENTS)\s*\.?\s*$", re.I)
TITLE_PAGE_SUBJECTS = re.compile(r"^SUBJECTS?\s*$", re.I)
QUESTION_LINE = re.compile(r"^QUESTION\s+\d+\.?\s*$", re.I)
BOOK_LINE = re.compile(r"^(?:BOOK|Book)\s+(?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|[IVXLC]+|\d+)\b", re.I)
ROMAN_SECTION = re.compile(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)\.\s*$")
CHAPTER_LINE = re.compile(r"^CHAPTER\s+[IVXLC\d]+", re.I)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def extract_title_page_toc(raw: str, *, max_chars: int = 8000) -> str:
    """PG pamphlet title-page topic list (e.g. Paine Common Sense SUBJECTS block)."""
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    block: list[str] = []
    in_subjects = False
    for line in lines[:180]:
        s = line.strip()
        if TITLE_PAGE_SUBJECTS.match(s):
            in_subjects = True
            block = []
            continue
        if not in_subjects:
            if re.match(r"^Of (?:the|Monarchy|Thoughts)\b", s, re.I) and len(s) < 120:
                block.append(s)
            elif re.match(r"^with concise Remarks\b", s, re.I):
                if block:
                    block[-1] = f"{block[-1]} {s}"
            continue
        if not s:
            if len(block) >= 2:
                break
            continue
        if "*** START" in s or s.startswith("***"):
            break
        if re.match(r"^(PHILADELPHIA|Printed|Man knows|MDCCL|Thomson)", s, re.I):
            break
        if len(s) < 140:
            block.append(s)
        if sum(len(x) + 1 for x in block) > max_chars:
            break
    return "\n".join(block)[:max_chars]


def parse_title_page_entries(raw: str) -> list[dict[str, Any]]:
    """Structured TOC entries from PG title page for PA2 content matching."""
    toc = extract_title_page_toc(raw)
    if not toc:
        return []
    entries: list[dict[str, Any]] = []
    for index, line in enumerate(toc.split("\n"), start=1):
        label = line.strip()
        if not label or len(label) < 8:
            continue
        upper = label.upper()
        entries.append(
            {
                "index": index,
                "label": label,
                "title": label,
                "match_strings": [label, upper, upper.rstrip(",.")],
                "kind": "chapter",
            }
        )
    return entries


def extract_toc_from_raw(raw: str, *, max_chars: int = 12000) -> str:
    """Full TOC block from PG raw text (before strip drops it)."""
    title_page = extract_title_page_toc(raw, max_chars=max_chars)
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start: int | None = None
    for i, line in enumerate(lines):
        if CONTENTS_HEAD.match(line.strip()) or line.strip().upper() == "CONTENTS":
            start = i
            break
    if start is None:
        # PG inline contents: " BOOK ONE.—..." cluster in first ~120 lines
        block: list[str] = []
        for i, line in enumerate(lines[:120]):
            s = line.strip()
            if not s:
                continue
            if is_toc_entry_line(s) or BOOK_LINE.match(s) or re.match(r"^[IVXLC]+\.", s):
                block.append(s)
            elif block and len(s) > 100:
                break
        inline = "\n".join(block)[:max_chars] if block else ""
        if title_page and inline:
            return f"{title_page}\n\n{inline}"[:max_chars]
        return title_page or inline

    out: list[str] = []
    for line in lines[start : start + 200]:
        s = line.strip()
        if not s and len(out) > 3:
            break
        if start != 0 and len(out) > 8 and len(s) > 110 and not is_toc_entry_line(s):
            break
        if is_toc_entry_line(s) or CONTENTS_HEAD.match(s) or BOOK_LINE.match(s) or not out:
            out.append(s)
        elif out and (is_chapter_heading_line(s) or re.match(r"^[IVXLC]+\.", s)):
            out.append(s)
        elif out and len(s) > 90:
            break
        if sum(len(x) + 1 for x in out) > max_chars:
            break
    return "\n".join(out)[:max_chars]


def detect_body_markers(text: str) -> list[dict[str, Any]]:
    """Deterministic body division markers in stripped text (ground-truth hint)."""
    markers: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.replace("\r\n", "\n").split("\n")):
        s = line.strip()
        if not s:
            continue
        kind: str | None = None
        if CHAPTER_LINE.match(s) or (is_body_heading_line(s) and "CHAPTER" in s.upper()):
            kind = "chapter"
        elif QUESTION_LINE.match(s):
            kind = "question"
        elif ROMAN_SECTION.match(s):
            kind = "roman_section"
        elif BOOK_LINE.match(s) and len(s) < 60:
            kind = "book"
        elif is_all_caps_body_section_line(s):
            if line_no == 0:
                continue
            if s.upper().startswith(("WITH ", "AND ")):
                continue
            kind = "all_caps_section"
        elif is_body_heading_line(s) and len(s) < 80:
            kind = "heading"
        if kind:
            markers.append({"line": line_no, "kind": kind, "text": s[:100]})
    return markers


def count_expected_body_divisions(markers: list[dict[str, Any]], *, prefer: str = "chapter") -> dict[str, Any]:
    """Best-effort expected body section count from markers."""
    by_kind: dict[str, int] = {}
    for m in markers:
        k = m["kind"]
        by_kind[k] = by_kind.get(k, 0) + 1
    if by_kind.get("chapter"):
        expected = by_kind["chapter"]
        basis = "chapter_lines"
    elif by_kind.get("all_caps_section"):
        expected = by_kind["all_caps_section"]
        basis = "all_caps_sections"
    elif by_kind.get("question"):
        expected = by_kind["question"]
        basis = "question_lines"
    elif by_kind.get("roman_section"):
        expected = by_kind["roman_section"]
        basis = "roman_sections"
    elif by_kind.get("book"):
        expected = by_kind["book"]
        basis = "book_lines"
    elif by_kind.get("heading"):
        expected = by_kind["heading"]
        basis = "heading_lines"
    else:
        expected = 0
        basis = "none"
    return {"expected_body_divisions": expected, "basis": basis, "by_kind": by_kind, "markers": markers}


def _body_sections(structure: dict[str, Any]) -> list[dict[str, Any]]:
    skip = {"front_matter", "back_matter", "other"}
    return [s for s in structure.get("sections") or [] if str(s.get("kind") or "") not in skip]


def _all_boundary_excerpts(
    text: str,
    structure: dict[str, Any],
    *,
    before: int = 80,
    after: int = 220,
) -> str:
    sections = structure.get("sections") or []
    if not sections:
        return "(no sections)"
    parts: list[str] = []
    for sec in sections:
        start = int(sec.get("start_char") or 0)
        lo = max(0, start - before)
        hi = min(len(text), start + after)
        excerpt = text[lo:hi].replace("\n", " ↵ ")
        parts.append(
            f"[{sec.get('section_id')}] L{sec.get('start_line')} {sec.get('kind')} "
            f"«{str(sec.get('title') or '')[:70]}»\n  ...{excerpt}...\n  {' ' * (before if start >= lo else 0)}^"
        )
    return "\n".join(parts)


def _llm_completeness_prompt(
    *,
    book_id: str,
    language: str,
    text_len: int,
    toc_full: str,
    structure: dict[str, Any],
    all_boundaries: str,
    expected: dict[str, Any],
    marker_table: str,
) -> list[dict[str, str]]:
    system = """You QA whether Step-1 macro segmentation is COMPLETE and CORRECT.

You receive:
- FULL table of contents (from publisher/Gutenberg, may include all chapter titles)
- Deterministic body markers found in stripped text (CHAPTER lines, roman I. II. III., BOOK lines)
- The macro LLM's full section list with start lines
- ALL boundary excerpts (^ = section start) — still NOT the full book prose

Your job: decide if macro sections cover EVERY body division implied by TOC + markers.

Rules:
- front_matter / preface before first body chapter is OK as its own section
- Do NOT count TOC lines as missing body chapters
- If TOC lists N body chapters but macro has fewer distinct body starts → incomplete (fail)
- If macro has extra splits inside a chapter with no heading → fail/warn
- If TOC absent, trust CHAPTER/roman/BOOK markers in stripped text

Return ONLY JSON:
{
  "summary_vi": "2-4 câu tiếng Việt",
  "complete": boolean,
  "verdict": "pass" | "warn" | "fail",
  "score": number,
  "toc_body_entries_estimate": number,
  "macro_body_sections": number,
  "missing": [{"title_or_marker": "...", "note_vi": "..."}],
  "extra": [{"section_id": "...", "note_vi": "..."}],
  "issues": [{"severity": "minor|major|critical", "note_vi": "..."}]
}
complete=true only if all TOC body chapters (or marker count) have a matching macro section start."""
    user = f"""Book: {book_id}
Language: {language}
Stripped length: {text_len} chars

Deterministic expected (hint): {json.dumps({k: expected[k] for k in expected if k != 'markers'}, ensure_ascii=False)}
Marker sample:
{marker_table}

--- FULL TOC (from raw / PG) ---
{toc_full or "(none — rely on markers)"}

--- MACRO STRUCTURE (mode={structure.get('mode')}, {structure.get('section_count')} sections) ---
content_kind: {structure.get('content_kind')}
summary_vi: {structure.get('summary_vi', '')}
{_section_table(structure)}

--- ALL BOUNDARY EXCERPTS ---
{all_boundaries}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def qa_macro_completeness(
    text: str,
    raw: str,
    structure: dict[str, Any],
    *,
    book_id: str,
    language: str = "en",
    use_llm: bool = True,
    model: str | None = None,
) -> dict[str, Any]:
    """Full TOC + all boundary excerpts QA for macro completeness."""
    markers = detect_body_markers(text)
    expected = count_expected_body_divisions(markers)
    toc_full = extract_toc_from_raw(raw) or _toc_excerpt(text, max_chars=12000)
    body_secs = _body_sections(structure)
    macro_body = body_secs
    marker_table = "\n".join(f"L{m['line']}\t{m['kind']}\t{m['text']}" for m in markers[:40])
    if len(markers) > 40:
        marker_table += f"\n... +{len(markers) - 40} markers"

    det_complete = (
        expected["expected_body_divisions"] > 0
        and len(macro_body) >= expected["expected_body_divisions"]
    )
    out: dict[str, Any] = {
        "book_id": book_id,
        "text_chars": len(text),
        "expected": expected,
        "toc_chars": len(toc_full),
        "macro_section_count": structure.get("section_count"),
        "macro_body_section_count": len(body_secs),
        "deterministic_complete": det_complete,
        "qa_at": _now(),
    }

    if not use_llm or not gemini_available():
        out["llm_qa"] = {"skipped": True}
        out["complete"] = det_complete
        return out

    qa_model = model or ref_llm_model()
    try:
        raw_resp = complete_chat(
            _llm_completeness_prompt(
                book_id=book_id,
                language=language,
                text_len=len(text),
                toc_full=toc_full,
                structure=structure,
                all_boundaries=_all_boundary_excerpts(text, structure),
                expected=expected,
                marker_table=marker_table,
            ),
            model=qa_model,
            temperature=0.1,
            max_tokens=4096,
        )
        parsed = parse_json_object(raw_resp)
        parsed["model"] = qa_model
        out["llm_qa"] = parsed
        out["complete"] = bool(parsed.get("complete"))
        out["verdict"] = parsed.get("verdict")
    except (ProviderError, ValueError, json.JSONDecodeError) as exc:
        out["llm_qa"] = {"error": str(exc), "model": qa_model}
        out["complete"] = det_complete
        out["verdict"] = "error"
    return out


def _section_table(structure: dict[str, Any]) -> str:
    rows: list[str] = []
    for sec in structure.get("sections") or []:
        rows.append(
            f"{sec.get('section_id')}\t{sec.get('kind')}\tL{sec.get('start_line')}\t"
            f"{sec.get('word_count', 0)}w\t{str(sec.get('title') or '')[:80]}"
        )
    return "\n".join(rows) if rows else "(empty)"


def _sample_boundary_excerpts(
    text: str,
    structure: dict[str, Any],
    *,
    max_sections: int = 8,
    before: int = 120,
    after: int = 380,
) -> str:
    sections = structure.get("sections") or []
    if not sections:
        return "(no sections)"
    if len(sections) <= max_sections:
        picked = sections
    else:
        step = max(1, len(sections) // max_sections)
        picked = [sections[i] for i in range(0, len(sections), step)][:max_sections]
        if sections[-1] not in picked:
            picked[-1] = sections[-1]

    parts: list[str] = []
    for sec in picked:
        start = int(sec.get("start_char") or 0)
        lo = max(0, start - before)
        hi = min(len(text), start + after)
        excerpt = text[lo:hi]
        marker = " " * (start - lo) + "^"
        parts.append(
            f"--- {sec.get('section_id')} ({sec.get('kind')}) L{sec.get('start_line')} "
            f"«{sec.get('title')}» ---\n{excerpt}\n{marker}\n"
        )
    return "\n".join(parts)


def _rule_preflight(
    text: str,
    rule_structure: dict[str, Any],
    *,
    language: str,
) -> dict[str, Any]:
    """Cheap checks before LLM — TOC lines treated as body starts."""
    candidates = scan_heading_candidates(text, language=language)
    toc_lines = {c["line"] for c in candidates if c.get("heuristic") == "toc_entry"}
    heading_lines = {c["line"] for c in candidates if c.get("heuristic") == "heading"}
    toc_as_starts = 0
    for sec in rule_structure.get("sections") or []:
        sl = int(sec.get("start_line") or -1)
        if sl in toc_lines and sl not in heading_lines:
            toc_as_starts += 1
    sections = rule_structure.get("sections") or []
    kinds: dict[str, int] = {}
    for sec in sections:
        k = str(sec.get("kind") or "other")
        kinds[k] = kinds.get(k, 0) + 1
    return {
        "section_count": len(sections),
        "toc_candidate_lines": len(toc_lines),
        "heading_candidate_lines": len(heading_lines),
        "rule_toc_line_used_as_start": toc_as_starts,
        "kinds": kinds,
    }


def _llm_macro_qa_prompt(
    *,
    book_id: str,
    language: str,
    family: str,
    text_len: int,
    toc_excerpt: str,
    rule_structure: dict[str, Any],
    llm_structure: dict[str, Any] | None,
    rule_boundaries: str,
    llm_boundaries: str | None,
    preflight: dict[str, Any],
) -> list[dict[str, str]]:
    llm_block = ""
    if llm_structure and llm_boundaries:
        llm_block = f"""
--- LLM STRUCTURE (mode={llm_structure.get('mode')}) ---
content_kind: {llm_structure.get('content_kind')}
summary_vi: {llm_structure.get('summary_vi', '')}
sections ({llm_structure.get('section_count')}):
{_section_table(llm_structure)}

--- LLM BOUNDARY EXCERPTS ---
{llm_boundaries}
"""
    system = """You QA Step-1 macro book segmentation for Knowledge Hub (chapter/section boundaries only — no block parse).

You receive TOC excerpt, compact section tables, and SHORT boundary excerpts (^ marks section start).
You do NOT receive the full book — infer from samples.

Evaluate RULE structure (always) and LLM structure (when provided):
- TOC/list lines mistaken as body chapter starts (dot leaders, page numbers, repeated titles)
- Missing real body chapters or parts
- front_matter vs first chapter boundary
- Absurd splits (100+ tiny sections, or 1 section for a long novel with clear TOC)
- content_kind plausibility (prose, verse, drama, scholastic, mixed)

Return ONLY JSON:
{
  "summary_vi": "2-4 câu tiếng Việt",
  "rule": {
    "verdict": "pass" | "warn" | "fail",
    "score": number,
    "issues": [{"severity": "minor|major|critical", "note_vi": "..."}]
  },
  "llm": {
    "verdict": "pass" | "warn" | "fail" | "skipped",
    "score": number | null,
    "better_than_rule": boolean | null,
    "issues": [{"severity": "minor|major|critical", "note_vi": "..."}]
  },
  "recommendation": "rule" | "llm" | "either"
}
Scores 1-10. fail if critical TOC/body confusion on rule or llm."""
    user = f"""Book: {book_id}
Language: {language}
Family: {family}
Stripped text length: {text_len} chars

Rule preflight: {json.dumps(preflight, ensure_ascii=False)}

--- TOC EXCERPT ---
{toc_excerpt or "(none)"}

--- RULE STRUCTURE (mode={rule_structure.get('mode')}) ---
content_kind: {rule_structure.get('content_kind', 'n/a')}
sections ({rule_structure.get('section_count')}):
{_section_table(rule_structure)}

--- RULE BOUNDARY EXCERPTS ---
{rule_boundaries}
{llm_block}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def qa_macro_pair(
    text: str,
    rule_structure: dict[str, Any],
    llm_structure: dict[str, Any] | None,
    *,
    book_id: str,
    language: str,
    family: str,
    use_llm: bool = True,
    model: str | None = None,
) -> dict[str, Any]:
    """QA rule vs optional LLM macro structures using boundary excerpts only."""
    preflight = _rule_preflight(text, rule_structure, language=language)
    toc = _toc_excerpt(text)
    rule_ex = _sample_boundary_excerpts(text, rule_structure)
    llm_ex = _sample_boundary_excerpts(text, llm_structure) if llm_structure else None

    out: dict[str, Any] = {
        "book_id": book_id,
        "language": language,
        "family": family,
        "text_chars": len(text),
        "preflight": preflight,
        "rule_section_count": rule_structure.get("section_count"),
        "llm_section_count": (llm_structure or {}).get("section_count"),
        "rule_mode": rule_structure.get("mode"),
        "llm_mode": (llm_structure or {}).get("mode"),
        "qa_at": _now(),
    }

    if not use_llm or not gemini_available():
        out["llm_qa"] = {"skipped": True, "reason": "no LLM"}
        out["passed"] = preflight.get("rule_toc_line_used_as_start", 0) == 0
        return out

    qa_model = model or ref_llm_model()
    try:
        raw = complete_chat(
            _llm_macro_qa_prompt(
                book_id=book_id,
                language=language,
                family=family,
                text_len=len(text),
                toc_excerpt=toc,
                rule_structure=rule_structure,
                llm_structure=llm_structure,
                rule_boundaries=rule_ex,
                llm_boundaries=llm_ex,
                preflight=preflight,
            ),
            model=qa_model,
            temperature=0.1,
            max_tokens=2048,
        )
        parsed = parse_json_object(raw)
        parsed["model"] = qa_model
        out["llm_qa"] = parsed
        rule_v = (parsed.get("rule") or {}).get("verdict")
        llm_v = (parsed.get("llm") or {}).get("verdict")
        out["passed"] = rule_v != "fail" and llm_v not in {"fail", None}
        out["recommendation"] = parsed.get("recommendation")
    except (ProviderError, ValueError, json.JSONDecodeError) as exc:
        out["llm_qa"] = {"error": str(exc), "model": qa_model}
        out["passed"] = False
    return out


def compare_structures(rule: dict[str, Any], llm: dict[str, Any]) -> dict[str, Any]:
    """Deterministic diff summary between rule and LLM macro outputs."""
    r_secs = rule.get("sections") or []
    l_secs = llm.get("sections") or []
    r_starts = [int(s.get("start_line") or 0) for s in r_secs]
    l_starts = [int(s.get("start_line") or 0) for s in l_secs]
    shared = len(set(r_starts) & set(l_starts))
    return {
        "rule_sections": len(r_secs),
        "llm_sections": len(l_secs),
        "shared_start_lines": shared,
        "rule_only_starts": len(set(r_starts) - set(l_starts)),
        "llm_only_starts": len(set(l_starts) - set(r_starts)),
        "section_count_delta": len(l_secs) - len(r_secs),
    }
