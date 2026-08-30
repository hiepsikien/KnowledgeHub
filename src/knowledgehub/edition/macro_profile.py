"""Heading profile induction (PA1: patterns, PA2: patterns + TOC content matching)."""

from __future__ import annotations

import json
import re
from typing import Any

from ..translation.llm_json import parse_json_object
from ..translation.providers import ProviderError, complete_chat
from .llm_defaults import gemini_available, ref_llm_model
from .macro import (
    _llm_macro_prompt,
    _rule_macro_structure,
    _sections_from_boundaries,
    _toc_excerpt,
    filter_candidates_for_llm,
    line_map,
    scan_heading_candidates,
)
from .macro_markers import try_marker_assembly
from .macro_qa import detect_body_markers, extract_toc_from_raw, parse_title_page_entries
from .toc import is_chapter_heading_line, is_toc_entry_line

ROMAN_SECTION = re.compile(
    r"^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX|XXI|XXII|XXIII|XXIV|XXV)\.\s*$"
)
QUESTION_LINE = re.compile(r"^QUESTION\s+\d+", re.I)
SECT_LINE = re.compile(r"^SECT\.?\s+[IVXLC\d]+", re.I)
LETTER_LINE = re.compile(r"^(?:Letter|LETTER)\s+(?:[IVXLC\d]+|\d+)", re.I)

_BUILTIN_EXTRA = (
    (ROMAN_SECTION, "roman_section"),
    (QUESTION_LINE, "question"),
    (SECT_LINE, "section"),
    (LETTER_LINE, "letter"),
)


def collect_profile_context(
    text: str,
    raw: str | None = None,
    *,
    language: str = "en",
    head_chars: int = 8000,
) -> dict[str, Any]:
    """Gather TOC + body heading samples for profile LLM calls."""
    toc_full = extract_toc_from_raw(raw or text) or _toc_excerpt(text, max_chars=12000)
    head = text[:head_chars]
    markers = detect_body_markers(text[: min(len(text), 120_000)])
    base_cands = scan_heading_candidates(text[: min(len(text), 120_000)], language=language)
    heading_lines = [c for c in base_cands if c.get("heuristic") == "heading"][:12]
    if not heading_lines and markers:
        rows = {r["line"]: r for r in line_map(text)}
        for m in markers[:12]:
            row = rows.get(m["line"])
            if row:
                heading_lines.append({**row, "text": m["text"], "heuristic": "marker"})

    body_sample = ""
    if heading_lines:
        first = int(heading_lines[0]["line"])
        rows = line_map(text)
        start = rows[first]["start"] if first < len(rows) else 0
        body_sample = text[start : start + 2500]

    return {
        "language": language,
        "text_len": len(text),
        "toc_full": toc_full,
        "head_excerpt": head,
        "body_sample": body_sample,
        "heading_examples": [str(c.get("text") or "")[:120] for c in heading_lines[:8]],
        "marker_examples": [m["text"] for m in markers[:12]],
    }


def _profile_prompt_base(*, pa2: bool) -> str:
    content_block = ""
    if pa2:
        content_block = """
Also extract TOC body entries (real chapters/sections in the book body, NOT imprint lines):
  "toc_body_entries": [
    {"index": 1, "label": "CHAPTER I", "title": "Short title if any", "match_strings": ["CHAPTER I", "Chapter I"]}
  ]
match_strings: exact/normalized strings to find this heading in body text."""
    return f"""You analyze a public-domain book's heading format for macro segmentation.

Given TOC excerpt, head of text, and heading examples, infer how body sections start.

Return ONLY JSON:
{{
  "summary_vi": "1-2 câu",
  "division_unit": "chapter|book|part|question|roman_section|letter|mixed",
  "content_kind": "prose|verse|scholastic|mixed|drama",
  "heading_rules": [
    {{"pattern": "^CHAPTER\\\\s+[IVXLC\\\\d]+", "kind": "chapter", "flags": "i", "example": "CHAPTER I"}}
  ],
  "body_heading_signals": ["standalone short line", "followed by blank line then prose"],
  "toc_dup_signals": ["dot leaders", "page number at end"]
}}{content_block}

Rules for heading_rules:
- Valid Python regex; anchor with ^ when line-start matters
- Include patterns for THIS book (roman I., QUESTION N, BOOK ONE, CHƯƠNG, etc.)
- Do not invent entries not supported by TOC/examples"""


def _infer_profile(
    context: dict[str, Any],
    *,
    pa2: bool,
    family: str,
    model: str | None = None,
) -> dict[str, Any]:
    if not gemini_available():
        raise ProviderError("Gemini not available for profile inference")
    qa_model = model or ref_llm_model()
    examples = "\n".join(f"- {x}" for x in context.get("heading_examples") or []) or "(none)"
    markers = "\n".join(f"- {x}" for x in context.get("marker_examples") or []) or "(none)"
    user = f"""Language: {context.get('language')}
Source family: {family}
Text length: {context.get('text_len')} chars

--- TOC ---
{context.get('toc_full') or '(none)'}

--- HEAD EXCERPT ---
{context.get('head_excerpt', '')[:6000]}

--- BODY SAMPLE (first heading region) ---
{context.get('body_sample') or '(none)'}

--- HEADING EXAMPLES ---
{examples}

--- DETERMINISTIC MARKERS ---
{markers}"""
    raw = complete_chat(
        [{"role": "system", "content": _profile_prompt_base(pa2=pa2)}, {"role": "user", "content": user}],
        model=qa_model,
        temperature=0.1,
        max_tokens=4096,
    )
    parsed = parse_json_object(raw)
    parsed["model"] = qa_model
    parsed["profile_mode"] = "pa2" if pa2 else "pa1"
    return parsed


def infer_profile_pa1(
    context: dict[str, Any],
    *,
    family: str,
    model: str | None = None,
) -> dict[str, Any]:
    return _infer_profile(context, pa2=False, family=family, model=model)


def infer_profile_pa2(
    context: dict[str, Any],
    *,
    family: str,
    model: str | None = None,
) -> dict[str, Any]:
    return _infer_profile(context, pa2=True, family=family, model=model)


def compile_profile_patterns(profile: dict[str, Any]) -> list[tuple[re.Pattern[str], str]]:
    compiled: list[tuple[re.Pattern[str], str]] = []
    for rule in profile.get("heading_rules") or []:
        if not isinstance(rule, dict):
            continue
        pat = str(rule.get("pattern") or "").strip()
        if not pat:
            continue
        flags = re.I if str(rule.get("flags") or "").lower() == "i" else 0
        try:
            compiled.append((re.compile(pat, flags), str(rule.get("kind") or "heading")))
        except re.error:
            continue
    return compiled


def _normalize_heading(text: str) -> str:
    s = text.strip()
    s = re.sub(r"\.{2,}\s*\d{0,4}$", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.upper()


def scan_extended_candidates(
    text: str,
    profile: dict[str, Any] | None,
    *,
    language: str = "en",
) -> list[dict[str, Any]]:
    """PA1/PA2 shared: baseline + built-in extras + profile regex patterns."""
    seen: dict[int, dict[str, Any]] = {}
    for cand in scan_heading_candidates(text, language=language):
        seen[int(cand["line"])] = cand

    rows = line_map(text)
    for row in rows:
        stripped = row["text"].strip()
        if not stripped or len(stripped) > 160:
            continue
        line_no = int(row["line"])
        if line_no in seen:
            continue
        for rx, kind in _BUILTIN_EXTRA:
            if rx.match(stripped):
                seen[line_no] = {**row, "text": stripped, "heuristic": "profile_builtin", "kind": kind}
                break

    for rx, kind in compile_profile_patterns(profile or {}):
        for row in rows:
            stripped = row["text"].strip()
            if not stripped or len(stripped) > 160:
                continue
            line_no = int(row["line"])
            if line_no in seen:
                continue
            if rx.search(stripped):
                seen[line_no] = {**row, "text": stripped, "heuristic": "profile_pattern", "kind": kind}

    return sorted(seen.values(), key=lambda c: int(c["line"]))


def scan_content_matches(
    text: str,
    profile: dict[str, Any],
    *,
    language: str = "en",
) -> list[dict[str, Any]]:
    """PA2: match TOC body entry labels/titles in stripped text."""
    entries = profile.get("toc_body_entries") or []
    if not entries:
        return []
    rows = line_map(text)
    line_text = {int(r["line"]): r["text"].strip() for r in rows}
    matched: dict[int, dict[str, Any]] = {}

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        needles: list[str] = []
        for key in ("label", "title"):
            val = str(entry.get(key) or "").strip()
            if val:
                needles.append(_normalize_heading(val))
        for ms in entry.get("match_strings") or []:
            val = str(ms).strip()
            if val:
                needles.append(_normalize_heading(val))
        needles = [n for n in dict.fromkeys(needles) if n]
        if not needles:
            continue

        for line_no, raw_line in line_text.items():
            if not raw_line or len(raw_line) > 160:
                continue
            norm = _normalize_heading(raw_line)
            if line_no in matched:
                continue
            if norm in needles or any(
                n == norm or (len(n) >= 8 and (n in norm or norm in n or norm.startswith(n[: min(24, len(n))])))
                for n in needles
            ):
                if is_toc_entry_line(raw_line) and not is_chapter_heading_line(raw_line):
                    if not any(is_chapter_heading_line(n) for n in [raw_line]):
                        continue
                row = rows[line_no]
                matched[line_no] = {
                    **row,
                    "text": raw_line,
                    "heuristic": "content_match",
                    "kind": str(entry.get("kind") or profile.get("division_unit") or "chapter"),
                    "toc_index": entry.get("index"),
                    "confidence": 0.88,
                }
                break

    return sorted(matched.values(), key=lambda c: int(c["line"]))


def _merge_toc_entries(profile: dict[str, Any], raw: str | None) -> dict[str, Any]:
    if not raw:
        return profile
    existing = profile.get("toc_body_entries") or []
    if len(existing) >= 3:
        return profile
    parsed = parse_title_page_entries(raw)
    if not parsed:
        return profile
    seen = {_normalize_heading(str(e.get("label") or "")) for e in existing if isinstance(e, dict)}
    merged = list(existing)
    for entry in parsed:
        key = _normalize_heading(str(entry.get("label") or ""))
        if key and key not in seen:
            merged.append(entry)
            seen.add(key)
    out = dict(profile)
    out["toc_body_entries"] = merged
    return out


def _looks_like_verse_excerpt(text: str, markers: list[dict[str, Any]]) -> bool:
    if markers:
        return False
    sample = text[:2000]
    lines = [ln.strip() for ln in sample.split("\n") if ln.strip()]
    if len(lines) < 8:
        return False
    tab_indented = sum(1 for ln in lines if ln.startswith("\t") or re.match(r"^\d+\t", ln))
    return tab_indented >= len(lines) * 0.25


def merge_candidates(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    priority = {
        "content_match": 3,
        "profile_pattern": 2,
        "profile_builtin": 2,
        "heading": 1,
        "marker": 1,
        "toc_entry": 0,
    }
    for group in groups:
        for cand in group:
            line_no = int(cand["line"])
            prev = merged.get(line_no)
            if prev is None or priority.get(str(cand.get("heuristic")), 0) >= priority.get(
                str(prev.get("heuristic")), 0
            ):
                merged[line_no] = cand
    return sorted(merged.values(), key=lambda c: int(c["line"]))


def _boundaries_from_content_matches(
    text: str,
    content_matches: list[dict[str, Any]],
    profile: dict[str, Any],
) -> list[dict[str, Any]] | None:
    entries = profile.get("toc_body_entries") or []
    if not content_matches or not entries:
        return None
    ratio = len(content_matches) / max(len(entries), 1)
    if ratio < 0.65:
        return None

    boundaries: list[dict[str, Any]] = []
    first_line = int(content_matches[0]["line"])
    if first_line > 0:
        boundaries.append(
            {"start_line": 0, "kind": "front_matter", "title": "Front matter", "confidence": 0.8}
        )
    unit = str(profile.get("division_unit") or "chapter")
    kind = unit if unit in {"chapter", "book", "part", "question", "roman_section", "letter"} else "chapter"
    for cand in content_matches:
        boundaries.append(
            {
                "start_line": int(cand["line"]),
                "heading_line": int(cand["line"]),
                "kind": str(cand.get("kind") or kind),
                "title": str(cand.get("text") or "Section"),
                "confidence": float(cand.get("confidence") or 0.85),
            }
        )
    return boundaries


def _should_use_content_bounds(
    content_matches: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    expected_body_divisions: int = 0,
) -> bool:
    entries = profile.get("toc_body_entries") or []
    if not content_matches or not entries:
        return False
    n_content = len(content_matches)
    n_entries = len(entries)
    if n_content < max(3, int(n_entries * 0.85)):
        return False
    if expected_body_divisions > 0 and n_content < int(expected_body_divisions * 0.85):
        return False
    return True


def build_structure_with_profile(
    text: str,
    *,
    language: str,
    family: str,
    profile: dict[str, Any],
    strategy: str,
    use_llm_boundaries: bool = True,
    model: str | None = None,
    expected_body_divisions: int = 0,
) -> dict[str, Any]:
    """Build macro structure using an inferred heading profile."""
    markers = detect_body_markers(text)
    marker_doc = try_marker_assembly(text, markers, language=language)
    if marker_doc is not None:
        marker_doc["profile_mode"] = strategy
        marker_doc["profile"] = _profile_summary(profile)
        marker_doc["summary_vi"] = str(profile.get("summary_vi") or marker_doc.get("summary_vi") or "")
        marker_doc["content_kind"] = str(profile.get("content_kind") or "prose")
        return marker_doc

    ext = scan_extended_candidates(text, profile, language=language)
    content: list[dict[str, Any]] = []
    if strategy == "pa2":
        content = scan_content_matches(text, profile, language=language)
    candidates = merge_candidates(ext, content)

    content_bounds = None
    if strategy == "pa2" and content:
        content_bounds = _boundaries_from_content_matches(text, content, profile)

    use_content = (
        strategy == "pa2"
        and content_bounds is not None
        and _should_use_content_bounds(
            content, profile, expected_body_divisions=expected_body_divisions
        )
    )

    if use_content:
        doc = _sections_from_boundaries(text, content_bounds or [], language=language)
        doc["mode"] = "pa2_content"
        doc["profile_mode"] = "pa2"
        doc["candidate_count"] = len(candidates)
        doc["content_match_count"] = len(content)
        doc["profile"] = _profile_summary(profile)
        doc["summary_vi"] = str(profile.get("summary_vi") or "")
        doc["content_kind"] = str(profile.get("content_kind") or "prose")
        return doc

    if use_llm_boundaries and gemini_available():
        qa_model = model or ref_llm_model()
        try:
            send = filter_candidates_for_llm(candidates)
            if len(send) > 400:
                hi = [c for c in send if c.get("heuristic") in {"content_match", "profile_pattern", "profile_builtin"}]
                rest = [c for c in send if c not in hi][: max(0, 400 - len(hi))]
                send = sorted(hi + rest, key=lambda c: int(c["line"]))
            raw_resp = complete_chat(
                _llm_macro_prompt(text=text, candidates=send, language=language, family=family),
                model=qa_model,
                temperature=0.1,
                max_tokens=8192,
            )
            parsed = parse_json_object(raw_resp)
            sections_in = parsed.get("sections") or []
            if not isinstance(sections_in, list) or not sections_in:
                raise ProviderError("boundary LLM returned no sections")
            doc = _sections_from_boundaries(text, sections_in, language=language)
            doc["mode"] = f"{strategy}_llm"
            doc["model"] = qa_model
            doc["profile_mode"] = strategy
            doc["candidate_count"] = len(candidates)
            doc["content_match_count"] = len(content)
            doc["profile"] = _profile_summary(profile)
            doc["summary_vi"] = str(parsed.get("summary_vi") or profile.get("summary_vi") or "")
            doc["content_kind"] = str(parsed.get("content_kind") or profile.get("content_kind") or "prose")
            return doc
        except (ProviderError, ValueError, json.JSONDecodeError) as exc:
            doc = _rule_macro_structure(text, candidates, language=language)
            doc["mode"] = f"{strategy}_rule_fallback"
            doc["llm_error"] = str(exc)
            doc["profile_mode"] = strategy
            doc["candidate_count"] = len(candidates)
            doc["content_match_count"] = len(content)
            doc["profile"] = _profile_summary(profile)
            return doc

    doc = _rule_macro_structure(text, candidates, language=language)
    doc["mode"] = f"{strategy}_rule"
    doc["profile_mode"] = strategy
    doc["candidate_count"] = len(candidates)
    doc["content_match_count"] = len(content)
    doc["profile"] = _profile_summary(profile)
    return doc


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "division_unit": profile.get("division_unit"),
        "content_kind": profile.get("content_kind"),
        "rule_count": len(profile.get("heading_rules") or []),
        "toc_entry_count": len(profile.get("toc_body_entries") or []),
        "profile_mode": profile.get("profile_mode"),
    }


def build_macro_with_strategy(
    text: str,
    raw: str | None,
    *,
    language: str,
    family: str,
    strategy: str,
    use_llm: bool = True,
    model: str | None = None,
) -> dict[str, Any]:
    """Entry: baseline | pa1 | pa2."""
    if strategy == "baseline":
        from .macro import build_macro_structure

        return build_macro_structure(
            text, language=language, family=family, use_llm=use_llm, model=model
        )

    context = collect_profile_context(text, raw, language=language)
    if strategy == "pa1":
        profile = infer_profile_pa1(context, family=family, model=model) if use_llm else {}
    elif strategy == "pa2":
        profile = infer_profile_pa2(context, family=family, model=model) if use_llm else {}
    else:
        raise ValueError(f"unknown macro strategy: {strategy}")

    if not use_llm:
        profile = profile or {}
    elif strategy == "pa2":
        profile = _merge_toc_entries(profile, raw)

    markers = detect_body_markers(text)
    if strategy == "pa2" and _looks_like_verse_excerpt(text, markers):
        profile = dict(profile)
        profile["content_kind"] = "verse"
        profile["toc_body_entries"] = []

    # Include APPENDIX/INTRODUCTION in pamphlet marker paths (handled in markers_at_level)

    from .macro_qa import count_expected_body_divisions

    expected = count_expected_body_divisions(markers)
    return build_structure_with_profile(
        text,
        language=language,
        family=family,
        profile=profile,
        strategy=strategy,
        use_llm_boundaries=use_llm,
        model=model,
        expected_body_divisions=int(expected.get("expected_body_divisions") or 0),
    )
