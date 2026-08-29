from __future__ import annotations

import os
from typing import Any

from ..translation.llm_json import parse_json_object
from .label_rules import LineLabel, uncertain_segment_indices
from .lines import TextLine

LLM_ROLES = frozenset(
    {
        "prose",
        "heading",
        "hr",
        "blockquote",
        "verse_line",
        "metadata",
        "toc",
        "dialogue_line",
        "speaker_cue",
        "stage_direction",
        "list_item",
    }
)


def _segment_prompt(lines: list[TextLine], labels: list[LineLabel], lo: int, hi: int) -> str:
    rows = []
    for i in range(lo, hi + 1):
        label = labels[i]
        rows.append(
            f'{i}: role={label.role} join_next={str(label.join_next).lower()} | {lines[i].text[:240]}'
        )
    return f"""Label each line of a public-domain book for reading layout (REF/1).

Allowed roles:
- prose, heading (level 1-4), hr, blockquote, verse_line, list_item
- metadata — TOC runs, front matter lists, imprint lines (not body chapter headings)
- dialogue_line + speaker_cue — drama; speaker_cue is the name line (e.g. HAMLET.)
- stage_direction — [Enter ...], stage notes
- toc — alias for metadata when line is clearly a contents entry

Set join_next true when the next line continues the same sentence/paragraph/stanza.

Return ONLY JSON:
{{"lines": [{{"index": 0, "role": "prose", "level": 0, "join_next": false, "confidence": 0.9}}]}}

Do NOT change any words — labels only.

--- LINES ---
""" + "\n".join(rows) + "\n--- END ---"


def relabel_segment_with_llm(
    lines: list[TextLine],
    labels: list[LineLabel],
    lo: int,
    hi: int,
    *,
    model: str | None = None,
) -> list[LineLabel]:
    try:
        from ..translation.providers import gemini_generate
    except ImportError:
        return labels

    prompt = _segment_prompt(lines, labels, lo, hi)
    try:
        raw = gemini_generate(
            prompt,
            system="You label book layout lines. Never rewrite text. JSON only.",
            model=model,
            temperature=0.1,
        )
        parsed = parse_json_object(raw)
    except Exception:
        return labels

    by_index = {label.index: label for label in labels}
    for row in parsed.get("lines") or []:
        if not isinstance(row, dict):
            continue
        idx = row.get("index")
        if not isinstance(idx, int) or idx < lo or idx > hi:
            continue
        role = str(row.get("role") or "")
        if role == "toc":
            role = "metadata"
        if role not in LLM_ROLES:
            continue
        level = int(row.get("level") or 0)
        join_next = bool(row.get("join_next"))
        confidence = float(row.get("confidence") or 0.85)
        by_index[idx] = LineLabel(
            index=idx,
            role=role,
            level=level if role == "heading" else None,
            join_next=join_next,
            confidence=min(1.0, max(0.0, confidence)),
            source="llm",
        )
    return [by_index[label.index] for label in labels]


def relabel_uncertain_segments(
    lines: list[TextLine],
    labels: list[LineLabel],
    *,
    enabled: bool = False,
    confidence_threshold: float = 0.8,
    model: str | None = None,
) -> tuple[list[LineLabel], list[dict[str, Any]]]:
    if not enabled:
        return labels, []
    events: list[dict[str, Any]] = []
    updated = labels
    for lo, hi in uncertain_segment_indices(labels, threshold=confidence_threshold):
        before = updated
        updated = relabel_segment_with_llm(lines, updated, lo, hi, model=model)
        events.append({"start": lo, "end": hi, "changed": before != updated})
    return updated, events
