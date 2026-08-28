from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


DROP_MIN_CONFIDENCE = 0.85


@dataclass(frozen=True)
class EditionSpan:
    start: int
    end: int
    kind: str
    action: str
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    ordered = sorted((a, b) for a, b in ranges if b > a)
    if not ordered:
        return []
    out = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = out[-1]
        if start <= prev_end:
            out[-1] = (prev_start, max(prev_end, end))
        else:
            out.append((start, end))
    return out


def apply_drops(text: str, spans: list[EditionSpan], *, min_confidence: float = DROP_MIN_CONFIDENCE) -> str:
    drops = merge_ranges(
        (s.start, s.end) for s in spans if s.action == "drop" and s.confidence >= min_confidence
    )
    if not drops:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end in drops:
        if start > cursor:
            parts.append(text[cursor:start])
        cursor = max(cursor, end)
    parts.append(text[cursor:])
    return "".join(parts)
