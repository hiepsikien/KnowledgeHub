"""Smart LLM QA for Step 1 macro structure — boundary excerpts only, not full book."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..translation.llm_json import parse_json_object
from ..translation.providers import ProviderError, complete_chat
from .llm_defaults import gemini_available, ref_llm_model
from .macro import _toc_excerpt, scan_heading_candidates, section_source_slice


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


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
