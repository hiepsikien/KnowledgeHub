"""HITL diagnostics and structure edits for Read Edition macro sections."""

from __future__ import annotations

import re
from typing import Any

from .macro import (
    SECTION_KINDS,
    _sections_from_boundaries,
    _toc_excerpt,
    line_map,
    scan_heading_candidates,
)
from .macro_qa import extract_toc_from_raw

SHORT_WORD_THRESHOLD = 80
SUPER_CHAR_SHARE = 0.35
INNER_HEADS_FOR_SUPER = 2
BOUNDARY_CONTEXT_LINES = 20
TOC_MATCH_MIN = 0.5

EXEMPT_SHORT_KINDS = frozenset({"front_matter", "notes", "back_matter", "preface"})
BODY_HEAD_HEURISTICS = frozenset(
    {"heading", "content_match", "profile_pattern", "profile_builtin", "marker"}
)
STRUCTURE_KEEP_KEYS = (
    "structure_version",
    "ref_parser_version",
    "language",
    "mode",
    "model",
    "summary_vi",
    "content_kind",
    "candidate_count",
    "work_id",
    "content_hash",
    "source_family",
    "division_level",
    "marker_count",
    "hitl",
    "llm_error",
)

_PAGE_TAIL = re.compile(r"\s+\d{1,4}$")
_NON_ALNUM = re.compile(r"[^a-z0-9àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ\s]+", re.I)


def normalize_toc_label(text: str) -> str:
    s = str(text or "").lower().replace("\u00a0", " ")
    s = re.sub(r"\.{2,}", " ", s)
    s = _PAGE_TAIL.sub("", s.strip())
    s = _NON_ALNUM.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def propose_toc_candidate(text: str, raw: str | None = None) -> dict[str, Any]:
    """Best TOC excerpt from raw (preferred) or stripped head. Status unset."""
    raw_toc = extract_toc_from_raw(raw) if raw else ""
    stripped_toc = _toc_excerpt(text)
    if raw_toc and len(raw_toc.strip()) >= 12:
        excerpt = raw_toc.strip()
        source = "raw"
        location = _toc_location(raw or text, excerpt)
    elif stripped_toc.strip():
        excerpt = stripped_toc.strip()
        source = "stripped"
        location = _toc_location(text, excerpt)
    else:
        return {
            "excerpt": "",
            "source": "none",
            "location": "none",
            "line_count": 0,
            "status": None,
        }
    lines = [ln for ln in excerpt.split("\n") if ln.strip()]
    return {
        "excerpt": excerpt,
        "source": source,
        "location": location,
        "line_count": len(lines),
        "status": None,
    }


def _toc_location(source: str, excerpt: str) -> str:
    first = next((ln.strip() for ln in excerpt.split("\n") if ln.strip()), "")
    if not first:
        return "none"
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for index, line in enumerate(lines):
        if first[:80] in line or line.strip()[:80] == first[:80]:
            if index <= 80:
                return "front"
            return "after_preface"
    return "front"


def toc_lines_from_hitl(structure: dict[str, Any]) -> list[str]:
    toc = (structure.get("hitl") or {}).get("toc") or {}
    excerpt = str(toc.get("excerpt") or "")
    return [ln.strip() for ln in excerpt.split("\n") if ln.strip()]


def _contained_as_words(needle: str, haystack: str) -> bool:
    """True when needle is a whole-word (space-delimited) substring of haystack."""
    if not needle or not haystack:
        return False
    return re.search(rf"(?:^|\s){re.escape(needle)}(?:$|\s)", haystack) is not None


def match_toc_line(title: str, toc_lines: list[str]) -> dict[str, Any] | None:
    needle = normalize_toc_label(title)
    if len(needle) < 4:
        return None
    best: dict[str, Any] | None = None
    best_score = 0.0
    for line in toc_lines:
        label = normalize_toc_label(line)
        if len(label) < 4:
            continue
        if needle == label:
            score = 1.0
        elif _contained_as_words(needle, label) or _contained_as_words(label, needle):
            # Word-boundary containment so "chapter i" does not hit "chapter ii".
            # Boost past TOC_MATCH_MIN: short titles vs long TOC lines fail a raw length ratio.
            score = max(
                min(len(needle), len(label)) / max(len(needle), len(label)),
                0.8,
            )
        else:
            continue
        if score > best_score:
            best_score = score
            best = {"label": line, "score": round(score, 3)}
    if best is None or best_score < TOC_MATCH_MIN:
        return None
    return best


def coverage_report(text: str, sections: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(text)
    if n <= 0:
        return {"complete": True, "orphan_chars": 0, "gaps": [], "overlaps": []}
    if not sections:
        return {
            "complete": False,
            "orphan_chars": n,
            "gaps": [{"start_char": 0, "end_char": n - 1}],
            "overlaps": [],
        }
    ordered = sorted(sections, key=lambda s: int(s.get("start_char") or 0))
    gaps: list[dict[str, int]] = []
    overlaps: list[dict[str, int]] = []
    first_start = int(ordered[0].get("start_char") or 0)
    if first_start > 0:
        gaps.append({"start_char": 0, "end_char": first_start - 1})
    for left, right in zip(ordered, ordered[1:]):
        left_end = int(left.get("end_char") or 0)
        right_start = int(right.get("start_char") or 0)
        if right_start > left_end + 1:
            gaps.append({"start_char": left_end + 1, "end_char": right_start - 1})
        elif right_start <= left_end:
            right_end = int(right.get("end_char") or 0)
            overlaps.append(
                {
                    "start_char": right_start,
                    "end_char": min(left_end, right_end),
                }
            )
    last_end = int(ordered[-1].get("end_char") or 0)
    if last_end < n - 1:
        gaps.append({"start_char": last_end + 1, "end_char": n - 1})
    orphan = sum(int(g["end_char"]) - int(g["start_char"]) + 1 for g in gaps)
    return {
        "complete": not gaps and not overlaps,
        "orphan_chars": orphan,
        "gaps": gaps,
        "overlaps": overlaps,
    }


def inner_heading_candidates(
    text: str,
    section: dict[str, Any],
    *,
    language: str = "en",
    candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    cands = candidates if candidates is not None else scan_heading_candidates(text, language=language)
    start_line = int(section.get("start_line") or 0)
    start_c = int(section.get("start_char") or 0)
    end_c = int(section.get("end_char") or 0)
    out: list[dict[str, Any]] = []
    for cand in cands:
        if int(cand.get("line") or -1) == start_line:
            continue
        if cand.get("heuristic") not in BODY_HEAD_HEURISTICS:
            continue
        pos = int(cand.get("start") or 0)
        if pos < start_c or pos > end_c:
            continue
        out.append(
            {
                "line": int(cand["line"]),
                "text": str(cand.get("text") or ""),
                "start": pos,
            }
        )
    return out


def _line_at_char(rows: list[dict[str, Any]], char_pos: int) -> int:
    for row in rows:
        if int(row["start"]) <= char_pos <= int(row["end"]):
            return int(row["line"])
    if not rows:
        return 0
    if char_pos <= int(rows[0]["start"]):
        return int(rows[0]["line"])
    return int(rows[-1]["line"])


def _join_lines(rows: list[dict[str, Any]], start_line: int, end_line: int) -> str:
    picked = [str(r.get("text") or "") for r in rows if start_line <= int(r["line"]) <= end_line]
    return "\n".join(picked)


def boundary_compare(
    rows: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    index: int,
    *,
    context_lines: int = BOUNDARY_CONTEXT_LINES,
) -> dict[str, str]:
    section = sections[index]
    start_line = int(section.get("start_line") or 0)
    end_line = _line_at_char(rows, int(section.get("end_char") or 0))
    prev_tail = ""
    next_head = ""
    if index > 0:
        prev = sections[index - 1]
        prev_end = _line_at_char(rows, int(prev.get("end_char") or 0))
        prev_start = int(prev.get("start_line") or 0)
        prev_tail = _join_lines(rows, max(prev_start, prev_end - context_lines + 1), prev_end)
    if index + 1 < len(sections):
        nxt = sections[index + 1]
        nxt_start = int(nxt.get("start_line") or 0)
        nxt_end = _line_at_char(rows, int(nxt.get("end_char") or 0))
        next_head = _join_lines(rows, nxt_start, min(nxt_end, nxt_start + context_lines - 1))
    this_head = _join_lines(rows, start_line, min(end_line, start_line + context_lines - 1))
    this_tail = _join_lines(rows, max(start_line, end_line - context_lines + 1), end_line)
    return {
        "prev_tail": prev_tail,
        "this_head": this_head,
        "this_tail": this_tail,
        "next_head": next_head,
    }


def _confirmed_starts(structure: dict[str, Any]) -> set[int]:
    hitl = structure.get("hitl") or {}
    return {int(x) for x in (hitl.get("confirmed_starts") or [])}


def diagnose_sections(
    text: str,
    structure: dict[str, Any],
    *,
    language: str | None = None,
) -> list[dict[str, Any]]:
    language = language or str(structure.get("language") or "en")
    sections = list(structure.get("sections") or [])
    rows = line_map(text)
    candidates = scan_heading_candidates(text, language=language)
    toc = (structure.get("hitl") or {}).get("toc") or {}
    toc_ok = toc.get("status") == "yes"
    toc_lines = toc_lines_from_hitl(structure) if toc_ok else []
    confirmed = _confirmed_starts(structure)
    total_chars = max(len(text), 1)
    out: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        start_c = int(section.get("start_char") or 0)
        end_c = int(section.get("end_char") or 0)
        span = max(end_c - start_c + 1, 0)
        share = span / total_chars
        kind = str(section.get("kind") or "chapter")
        words = int(section.get("word_count") or 0)
        inner = inner_heading_candidates(text, section, language=language, candidates=candidates)
        flags: list[str] = []
        short = words < SHORT_WORD_THRESHOLD and kind not in EXEMPT_SHORT_KINDS
        super_sec = share >= SUPER_CHAR_SHARE and len(inner) >= INNER_HEADS_FOR_SUPER
        if short:
            flags.append("short")
        if super_sec:
            flags.append("super")
        if inner:
            flags.append("inner_heads")
        toc_hit = match_toc_line(str(section.get("title") or ""), toc_lines) if toc_lines else None
        if toc_ok and kind in {"chapter", "part", "book"}:
            if toc_hit:
                flags.append("toc_hit")
            else:
                flags.append("toc_miss")
        start_line = int(section.get("start_line") or 0)
        out.append(
            {
                **section,
                "flags": flags,
                "inner_heads": inner,
                "inner_head_count": len(inner),
                "char_share": round(share, 4),
                "toc_match": toc_hit,
                "confirmed": start_line in confirmed,
                "compare": boundary_compare(rows, sections, index),
            }
        )
    return out


def build_review(
    text: str,
    structure: dict[str, Any],
    *,
    raw: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    language = language or str(structure.get("language") or "en")
    hitl = dict(structure.get("hitl") or {})
    toc = dict(hitl.get("toc") or {})
    if not toc.get("excerpt"):
        proposed = propose_toc_candidate(text, raw)
        toc = {**proposed, "status": toc.get("status")}
    sections = diagnose_sections(text, {**structure, "hitl": {**hitl, "toc": toc}}, language=language)
    coverage = coverage_report(text, structure.get("sections") or [])
    untreated = [
        s["section_id"]
        for s in sections
        if (not s.get("confirmed")) and ({"short", "super"} & set(s.get("flags") or []))
    ]
    toc_status = toc.get("status")
    toc_answered = toc_status in {"yes", "no", "none"}
    layout_ok = bool(hitl.get("layout_ok"))
    ready = bool(toc_answered and not untreated and coverage.get("complete"))
    return {
        "toc_candidate": toc,
        "coverage": coverage,
        "sections": sections,
        "health": {
            "short": sum(1 for s in sections if "short" in (s.get("flags") or [])),
            "super": sum(1 for s in sections if "super" in (s.get("flags") or [])),
            "inner_heads": sum(1 for s in sections if "inner_heads" in (s.get("flags") or [])),
            "toc_miss": sum(1 for s in sections if "toc_miss" in (s.get("flags") or [])),
            "untreated_flags": untreated,
            "toc_answered": toc_answered,
            "layout_ok": layout_ok,
            "ready_to_parse": ready,
            "not_ready_reason": None if ready else structure_not_ready_reason(toc_answered, untreated, coverage),
        },
        "hitl": {**hitl, "toc": toc},
    }


def structure_not_ready_reason(
    toc_answered: bool,
    untreated: list[str],
    coverage: dict[str, Any],
) -> str:
    parts: list[str] = []
    if not toc_answered:
        parts.append("TOC not confirmed")
    if untreated:
        parts.append(f"{len(untreated)} short/super section(s) unconfirmed")
    if not coverage.get("complete"):
        parts.append("coverage incomplete (gaps or overlaps)")
    return "Structure not ready to parse — " + ("; ".join(parts) or "HITL review incomplete")


def sections_to_boundaries(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bounds: list[dict[str, Any]] = []
    for section in sections:
        bounds.append(
            {
                "start_line": int(section["start_line"]),
                "heading_line": section.get("heading_line", section.get("start_line")),
                "kind": str(section.get("kind") or "chapter"),
                "title": str(section.get("title") or "Section"),
                "subtitle": section.get("subtitle"),
                "confidence": float(section.get("confidence") or 0.85),
            }
        )
    return bounds


def _copy_envelope(old: dict[str, Any], rebuilt: dict[str, Any]) -> dict[str, Any]:
    out = dict(rebuilt)
    for key in STRUCTURE_KEEP_KEYS:
        if key in old and key not in {"structure_version", "ref_parser_version", "language"}:
            out[key] = old[key]
        elif key in old and key not in out:
            out[key] = old[key]
    out["language"] = rebuilt.get("language") or old.get("language")
    if "hitl" in old:
        out["hitl"] = old["hitl"]
    return out


def _heading_title(text: str, start_line: int, *, language: str) -> str:
    for cand in scan_heading_candidates(text, language=language):
        if int(cand.get("line") or -1) == start_line:
            return str(cand.get("text") or f"Section {start_line}")
    rows = line_map(text)
    for row in rows:
        if int(row["line"]) == start_line:
            return str(row.get("text") or "").strip() or f"Section {start_line}"
    return f"Section {start_line}"


def apply_structure_edit(
    text: str,
    structure: dict[str, Any],
    *,
    action: str,
    section_id: str,
    start_line: int | None = None,
    kind: str | None = None,
    language: str | None = None,
) -> tuple[dict[str, Any], int]:
    """Apply a curator edit. Returns (new_structure, focused_start_line)."""
    language = language or str(structure.get("language") or "en")
    sections = list(structure.get("sections") or [])
    if not sections:
        raise ValueError("no sections to edit")
    index = next((i for i, s in enumerate(sections) if s.get("section_id") == section_id), None)
    if index is None:
        raise ValueError(f"Unknown section: {section_id}")
    focused = int(sections[index]["start_line"])
    hitl = dict(structure.get("hitl") or {})
    confirmed = {int(x) for x in (hitl.get("confirmed_starts") or [])}

    if action == "confirm":
        confirmed.add(int(sections[index]["start_line"]))
        hitl["confirmed_starts"] = sorted(confirmed)
        out = dict(structure)
        out["hitl"] = hitl
        return out, focused

    if action == "set_kind":
        if not kind:
            raise ValueError("kind required for set_kind")
        kind_norm = str(kind).lower()
        if kind_norm not in SECTION_KINDS:
            raise ValueError(f"unknown kind: {kind}")
        sections[index] = {**sections[index], "kind": kind_norm}
        out = dict(structure)
        out["sections"] = sections
        out["hitl"] = hitl
        return out, focused
    if action == "merge_prev":
        if index == 0:
            raise ValueError("cannot merge first section with previous")
        focused = int(sections[index - 1]["start_line"])
        del sections[index]
    elif action == "merge_next":
        if index + 1 >= len(sections):
            raise ValueError("cannot merge last section with next")
        focused = int(sections[index]["start_line"])
        del sections[index + 1]
    elif action == "drop_start":
        if index == 0:
            if int(sections[0]["start_line"]) == 0:
                raise ValueError("first section already starts at line 0")
            sections[0] = {
                **sections[0],
                "start_line": 0,
                "heading_line": 0,
                "kind": "front_matter",
                "title": "Front matter",
            }
            focused = 0
        else:
            focused = int(sections[index - 1]["start_line"])
            del sections[index]
    elif action == "split_at":
        if start_line is None:
            raise ValueError("start_line required for split_at")
        split_line = int(start_line)
        cur_start = int(sections[index]["start_line"])
        next_start = (
            int(sections[index + 1]["start_line"])
            if index + 1 < len(sections)
            else _line_at_char(line_map(text), len(text) - 1 if text else 0) + 1
        )
        if split_line <= cur_start or split_line >= next_start:
            raise ValueError("split_at line must lie strictly inside the section")
        title = _heading_title(text, split_line, language=language)
        sections.insert(
            index + 1,
            {
                "start_line": split_line,
                "heading_line": split_line,
                "kind": "chapter",
                "title": title,
                "subtitle": None,
                "confidence": 0.9,
            },
        )
        focused = split_line
    else:
        raise ValueError(f"unknown action: {action}")

    rebuilt = _sections_from_boundaries(text, sections_to_boundaries(sections), language=language)
    out = _copy_envelope(structure, rebuilt)
    still = sorted(s for s in confirmed if any(int(sec["start_line"]) == s for sec in rebuilt.get("sections") or []))
    hitl["confirmed_starts"] = still
    hitl["layout_ok"] = False
    out["hitl"] = hitl
    return out, focused
