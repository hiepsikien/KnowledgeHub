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
from .toc import is_all_caps_section_line, is_body_heading_line, is_chapter_heading_line, is_toc_entry_line

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
        "notes",
        "toc",
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

VI_CHAPTER = re.compile(
    r"^CHƯƠNG\s+(?:[IVXLC\d]+|Một|Hai|Ba|Bốn|Tư|Năm|Sáu|Bảy|Tám|Chín|Mười)(?:[^\n]{0,40})?$",
    re.I,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _same_heading(left: str, right: str) -> bool:
    def norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()

    a, b = norm(left), norm(right)
    return bool(a) and a == b


def line_map(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pos = 0
    for index, part in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
        start = pos
        end = pos + len(part)
        rows.append({"line": index, "start": start, "end": end, "text": part})
        pos = end + 1
    return rows


ESSAY_SECTION = re.compile(
    r"^(?:What (?:Is|Are|Ought)|The (?:Law|Complete|Solution|Conclusion)|Property and)\b",
    re.I,
)


def scan_heading_candidates(text: str, *, language: str = "en") -> list[dict[str, Any]]:
    lang = (language or "en").lower()[:2]
    rows = line_map(text)
    out: list[dict[str, Any]] = []
    for row in rows:
        stripped = row["text"].strip()
        if not stripped or len(stripped) > 160:
            continue
        if is_body_heading_line(stripped):
            out.append({**row, "text": stripped, "heuristic": "heading"})
            continue
        if is_all_caps_section_line(stripped):
            out.append({**row, "text": stripped, "heuristic": "heading", "kind": "all_caps_section"})
            continue
        if ESSAY_SECTION.match(stripped) and len(stripped) < 80:
            out.append({**row, "text": stripped, "heuristic": "heading", "kind": "section"})
            continue
        if is_toc_entry_line(stripped):
            out.append({**row, "text": stripped, "heuristic": "toc_entry"})
            continue
        if HEADING_CANDIDATE.match(stripped):
            out.append({**row, "text": stripped, "heuristic": "heading"})
            continue
        if lang == "vi" and VI_CHAPTER.match(stripped):
            out.append({**row, "text": stripped, "heuristic": "heading"})
    return out


def filter_candidates_for_llm(candidates: list[dict[str, Any]], *, limit: int = 500) -> list[dict[str, Any]]:
    """Drop noisy toc_entry rows; prefer body headings for boundary LLM."""
    keep_heuristics = {
        "heading",
        "content_match",
        "profile_pattern",
        "profile_builtin",
        "marker",
    }
    body = [c for c in candidates if c.get("heuristic") in keep_heuristics]
    if len(body) >= 5:
        return body[:limit]
    # sparse headings — include toc_entry chapter rows as fallback
    fallback = [c for c in candidates if c.get("heuristic") == "toc_entry" and is_chapter_heading_line(str(c.get("text") or ""))]
    merged = {int(c["line"]): c for c in body + fallback}
    return sorted(merged.values(), key=lambda c: int(c["line"]))[:limit]


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


def _normalize_llm_boundaries(
    boundaries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    max_snap_distance: int = 5,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Snap LLM boundary lines to candidate lines; None → caller should rule_fallback."""
    cand_lines = sorted({int(c["line"]) for c in candidates})
    if not cand_lines:
        return None, "no heading candidates"
    allowed = set(cand_lines) | {0}
    normalized: list[dict[str, Any]] = []
    invalid = 0
    for bound in boundaries:
        if not isinstance(bound, dict):
            invalid += 1
            continue
        start_line = int(bound.get("start_line", -1))
        if start_line in allowed:
            normalized.append(bound)
            continue
        nearest = min(cand_lines, key=lambda line: abs(line - start_line))
        if abs(nearest - start_line) <= max_snap_distance:
            fixed = dict(bound)
            fixed["start_line"] = nearest
            if bound.get("heading_line") is not None:
                fixed["heading_line"] = nearest
            normalized.append(fixed)
            continue
        invalid += 1
    if invalid:
        return None, f"{invalid} boundary start_line values not in candidates"
    seen: set[int] = set()
    deduped: list[dict[str, Any]] = []
    for bound in sorted(normalized, key=lambda b: int(b["start_line"])):
        start_line = int(bound["start_line"])
        if start_line in seen:
            continue
        seen.add(start_line)
        deduped.append(bound)
    if not deduped:
        return None, "no valid boundaries after normalization"
    return deduped, None


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
        if start_line not in line_to_start:
            raise ValueError(f"unknown start_line {start_line} — not in source line map")
        start_char = int(line_to_start[start_line])
        if index + 1 < len(ordered):
            next_line = int(ordered[index + 1]["start_line"])
            if next_line not in line_to_start:
                raise ValueError(f"unknown start_line {next_line} — not in source line map")
            end_char = int(line_to_start[next_line]) - 1
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
    body_heuristics = {"heading", "content_match", "profile_pattern", "profile_builtin", "marker"}
    body = [c for c in candidates if c.get("heuristic") in body_heuristics]
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
        for c in filter_candidates_for_llm(candidates)
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
    strategy: str = "baseline",
    raw: str | None = None,
) -> dict[str, Any]:
    """Step 1 — section boundaries on stripped source text (one LLM call, no block parse).

    strategy: baseline (legacy) | pa1 (LLM heading patterns) | pa2 (patterns + TOC content match)
    raw: optional unstripped source for TOC extraction (required for best pa1/pa2 results).
    """
    if not text.strip():
        raise ValueError("empty text for macro structure")
    family = family or detect_family(text, work=work, language=language)
    if strategy not in {"baseline", "pa1", "pa2"}:
        raise ValueError(f"unknown macro strategy: {strategy}")
    if strategy in {"pa1", "pa2"}:
        from .macro_profile import build_macro_with_strategy

        return build_macro_with_strategy(
            text,
            raw,
            language=language,
            family=family,
            strategy=strategy,
            use_llm=use_llm,
            model=model,
        )
    candidates = scan_heading_candidates(text, language=language)

    from .macro_markers import try_marker_assembly
    from .macro_qa import detect_body_markers
    from .toc import (
        match_toc_entries_in_body,
        parse_contents_entries,
        toc_is_wrap_page_column,
        toc_match_covers_structure,
    )

    toc_source = raw or text
    toc_entries = parse_contents_entries(toc_source)
    toc_matched = match_toc_entries_in_body(text, toc_entries) if toc_entries else []
    if (
        toc_is_wrap_page_column(toc_entries)
        and toc_match_covers_structure(toc_entries, toc_matched)
    ):
        boundaries: list[dict[str, Any]] = []
        if int(toc_matched[0]["line"]) > 0:
            boundaries.append(
                {"start_line": 0, "kind": "front_matter", "title": "Front matter", "confidence": 0.85}
            )
        for row in toc_matched:
            title = str(row.get("text") or row.get("label") or "Section")
            subtitle = str(row.get("title") or "")
            if _same_heading(subtitle, title) or _same_heading(subtitle, str(row.get("label") or "")):
                subtitle_out = None
            else:
                subtitle_out = subtitle[:180] or None
            boundaries.append(
                {
                    "start_line": int(row["line"]),
                    "heading_line": int(row["line"]),
                    "kind": str(row.get("kind") or "chapter"),
                    "title": title,
                    "subtitle": subtitle_out,
                    "confidence": 0.93,
                }
            )
        doc = _sections_from_boundaries(text, boundaries, language=language)
        doc["mode"] = "toc_match"
        doc["candidate_count"] = len(candidates)
        doc["content_kind"] = "prose"
        doc["toc_entry_count"] = len(toc_entries)
        doc["toc_matched_count"] = len(toc_matched)
        doc["summary_vi"] = (
            f"Phân đoạn từ mục lục ({len(toc_matched)}/{len(toc_entries)} mục khớp trong body)."
        )
        return doc

    markers = detect_body_markers(text)
    marker_doc = try_marker_assembly(text, markers, language=language)
    if marker_doc is not None:
        marker_doc["candidate_count"] = len(candidates)
        marker_doc["content_kind"] = marker_doc.get("content_kind") or "prose"
        marker_doc["summary_vi"] = marker_doc.get("summary_vi") or (
            f"Phân đoạn deterministic từ {marker_doc.get('marker_count')} marker ({marker_doc.get('division_level')})."
        )
        return marker_doc

    if use_llm and gemini_available():
        qa_model = model or ref_llm_model()
        try:
            raw_resp = complete_chat(
                _llm_macro_prompt(text=text, candidates=candidates, language=language, family=family),
                model=qa_model,
                temperature=0.1,
                max_tokens=8192,
            )
            parsed = parse_json_object(raw_resp)
            sections_in = parsed.get("sections") or []
            if not isinstance(sections_in, list) or not sections_in:
                raise ProviderError("macro LLM returned no sections")
            llm_candidates = filter_candidates_for_llm(candidates)
            normalized, norm_err = _normalize_llm_boundaries(sections_in, llm_candidates)
            if normalized is None:
                raise ProviderError(norm_err or "invalid LLM boundaries")
            doc = _sections_from_boundaries(text, normalized, language=language)
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
