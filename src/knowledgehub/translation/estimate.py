"""Rough LLM token estimates for the missing-draft confirm (not a billing meter).

Uses ``segment.words``. Older chapters missing that field undercount source tokens;
prompt overhead still applies. Acceptable for a heuristic."""

from __future__ import annotations

from collections import Counter
from typing import Any

REASON_LABELS = {
    "empty": "chưa có nháp",
    "raw_pending": "có nháp thô, chưa polish",
    "truncated": "bản dịch cụt",
    "incomplete_parts": "thiếu phần",
    "polish_pending": "chờ polish",
}

# chars/4 is a common Latin-script heuristic; VI output is a bit denser.
TOKENS_PER_WORD = 4 / 3
OUTPUT_RATIO = 1.15
PROMPT_OVERHEAD = 2500
FOLLOWUP_IN = 2000
FOLLOWUP_OUT = 2200


def estimate_tokens_from_words(words: int) -> int:
    return max(1, int(round(max(0, words) * TOKENS_PER_WORD)))


def format_token_estimate(n: int) -> str:
    if n >= 1_000_000:
        return f"~{n / 1_000_000:.1f} triệu".replace(".", ",")
    if n >= 10_000:
        return f"~{n // 1000} nghìn"
    return f"~{n}"


def missing_reason(row: dict[str, Any]) -> str:
    completeness = str(row.get("completeness") or "missing")
    if completeness == "missing" and row.get("has_draft_raw"):
        return "raw_pending"
    if completeness == "missing":
        return "empty"
    return completeness


def _chapter_tokens(row: dict[str, Any], *, auto_annotate: bool, auto_qa: bool) -> tuple[int, dict[str, int]]:
    src = estimate_tokens_from_words(int(row.get("words") or 0))
    out = max(1, int(round(src * OUTPUT_RATIO)))
    reason = missing_reason(row)
    polish_only = reason in {"polish_pending", "raw_pending"}
    calls = {"draft": 0, "polish": 1, "annotate": 0, "qa": 0}
    tokens = PROMPT_OVERHEAD + src + out + out  # polish in (src+draft) + out
    if not polish_only:
        calls["draft"] = 1
        tokens += PROMPT_OVERHEAD + src + out
    if auto_annotate:
        calls["annotate"] = 1
        tokens += FOLLOWUP_IN + min(src, 6000) + FOLLOWUP_OUT
    if auto_qa:
        calls["qa"] = 1
        tokens += FOLLOWUP_IN + min(src, 8000) + FOLLOWUP_OUT
    return tokens, calls


def missing_draft_preview(
    chapters: list[dict[str, Any]],
    *,
    auto_annotate: bool = True,
    auto_qa: bool = True,
) -> dict[str, Any]:
    missing = [row for row in chapters if str(row.get("completeness") or "missing") != "ok"]
    reasons: Counter[str] = Counter()
    calls: Counter[str] = Counter()
    total = 0
    words = 0
    for row in missing:
        reasons[missing_reason(row)] += 1
        words += int(row.get("words") or 0)
        chapter_tokens, chapter_calls = _chapter_tokens(
            row, auto_annotate=auto_annotate, auto_qa=auto_qa
        )
        total += chapter_tokens
        calls.update(chapter_calls)
    by_reason = [
        {
            "reason": reason,
            "label": REASON_LABELS.get(reason, reason),
            "count": count,
        }
        for reason, count in reasons.most_common()
    ]
    return {
        "count": len(missing),
        "source_words": words,
        "est_tokens": total,
        "est_tokens_label": format_token_estimate(total),
        "by_reason": by_reason,
        "calls": dict(calls),
        "auto_annotate": auto_annotate,
        "auto_qa": auto_qa,
        "note": "Ước lượng thô (chars/word heuristic), không phải số token billing.",
    }
