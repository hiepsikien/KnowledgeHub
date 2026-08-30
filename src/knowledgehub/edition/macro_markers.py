"""Deterministic macro assembly from body markers (P0/P1)."""

from __future__ import annotations

from typing import Any

from .macro import _sections_from_boundaries

MIN_MARKER_COUNT = 5
_KIND_TO_SECTION = {
    "chapter": "chapter",
    "book": "book",
    "roman_section": "chapter",
    "question": "chapter",
    "section": "chapter",
    "all_caps_section": "chapter",
    "heading": "chapter",
    "letter": "chapter",
}


def resolve_division_level(markers: list[dict[str, Any]]) -> str:
    """Pick finest reliable division level from marker histogram."""
    by_kind: dict[str, int] = {}
    for m in markers:
        k = str(m.get("kind") or "heading")
        by_kind[k] = by_kind.get(k, 0) + 1

    chapters = by_kind.get("chapter", 0)
    questions = by_kind.get("question", 0)
    romans = by_kind.get("roman_section", 0)
    books = by_kind.get("book", 0)
    caps = by_kind.get("all_caps_section", 0)
    sections = by_kind.get("section", 0)

    if chapters >= MIN_MARKER_COUNT:
        return "chapter"
    if chapters >= 2 and chapters >= caps:
        return "chapter"
    if chapters >= 2 and caps > chapters * 5:
        return "chapter"
    if questions >= 3:
        return "question"
    if books >= 2 and books >= max(romans, caps, sections):
        return "book"
    if romans >= 2:
        return "roman_section"
    if caps >= 2 and caps > books:
        return "all_caps_section"
    if sections >= 2:
        return "section"
    if books >= 2 and chapters < MIN_MARKER_COUNT:
        return "book"
    if chapters >= 1:
        return "chapter"
    if romans >= 1:
        return "roman_section"
    if caps >= 1:
        return "all_caps_section"
    if books >= 1:
        return "book"
    return "chapter"


def markers_at_level(markers: list[dict[str, Any]], level: str) -> list[dict[str, Any]]:
    if level == "book":
        return [m for m in markers if m.get("kind") == "book"]
    if level == "all_caps_section":
        body = [m for m in markers if m.get("kind") == "all_caps_section"]
        for m in markers:
            if m.get("kind") != "heading":
                continue
            title = str(m.get("text") or "").upper()
            if title.startswith(("INTRODUCTION", "APPENDIX", "PREFACE", "EPILOGUE")):
                body.append(m)
        return sorted(body, key=lambda x: int(x["line"]))
    if level in {"chapter", "question", "roman_section", "section", "all_caps_section"}:
        kind_map = {
            "chapter": {"chapter", "heading"},
            "question": {"question"},
            "roman_section": {"roman_section"},
            "section": {"section"},
            "all_caps_section": {"all_caps_section"},
        }
        allowed = kind_map.get(level, {level})
        return [m for m in markers if m.get("kind") in allowed]
    return list(markers)


def should_use_marker_assembly(markers: list[dict[str, Any]], *, level: str | None = None) -> bool:
    level = level or resolve_division_level(markers)
    selected = markers_at_level(markers, level)
    if level in {"all_caps_section", "roman_section", "section"}:
        return len(selected) >= 2
    if level == "book":
        return len(selected) >= 2
    if level in {"chapter", "question"}:
        return len(selected) >= 3
    return len(selected) >= MIN_MARKER_COUNT


def build_structure_from_markers(
    text: str,
    markers: list[dict[str, Any]],
    *,
    language: str,
    level: str | None = None,
) -> dict[str, Any]:
    level = level or resolve_division_level(markers)
    body = markers_at_level(markers, level)
    if not body:
        body = list(markers)
    boundaries: list[dict[str, Any]] = []
    first_line = int(body[0]["line"])
    if first_line > 0:
        boundaries.append(
            {"start_line": 0, "kind": "front_matter", "title": "Front matter", "confidence": 0.85}
        )
    sec_kind = _KIND_TO_SECTION.get(level, "chapter")
    for m in body:
        boundaries.append(
            {
                "start_line": int(m["line"]),
                "heading_line": int(m["line"]),
                "kind": sec_kind,
                "title": str(m.get("text") or "Section"),
                "confidence": 0.92,
            }
        )
    doc = _sections_from_boundaries(text, boundaries, language=language)
    doc["division_level"] = level
    doc["marker_count"] = len(body)
    return doc


def try_marker_assembly(
    text: str,
    markers: list[dict[str, Any]],
    *,
    language: str,
) -> dict[str, Any] | None:
    if not markers:
        return None
    level = resolve_division_level(markers)
    if not should_use_marker_assembly(markers, level=level):
        return None
    doc = build_structure_from_markers(text, markers, language=language, level=level)
    doc["mode"] = "markers"
    return doc
