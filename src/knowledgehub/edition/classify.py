from __future__ import annotations

from typing import Any

from ..translation.llm_json import parse_json_object
from .spans import DROP_MIN_CONFIDENCE, EditionSpan


def classify_unsure_spans(
    text: str,
    spans: list[EditionSpan],
    *,
    enabled: bool = False,
) -> list[EditionSpan]:
    """Optional cheap LLM gate: only spans that would be dropped if we lowered the bar.

    Does not rewrite prose. Missing API keys leave spans unchanged.
    """
    if not enabled:
        return spans
    candidates = [
        s
        for s in spans
        if s.action == "drop" and 0.55 <= s.confidence < DROP_MIN_CONFIDENCE
    ]
    if not candidates:
        return spans
    try:
        from ..translation.providers import gemini_generate
    except ImportError:
        return spans

    resolved: list[EditionSpan] = []
    by_id = {(s.start, s.end, s.kind): s for s in spans}
    for span in candidates:
        excerpt = text[span.start : span.end][:2500]
        prompt = f"""You classify a text span from a public-domain book scan.

Kind guess: {span.kind}
Reason: {span.reason}

Is this span part of the literary work (preface, chapter, author notes),
or non-work apparatus (Gutenberg wrapper, table of contents list, paper index,
library stamp, transcriber note)?

Return ONLY JSON: {{"action": "keep" | "drop", "confidence": 0.0-1.0}}

--- SPAN ---
{excerpt}
--- END SPAN ---
"""
        try:
            raw = gemini_generate(
                prompt,
                system="You label edition spans. Never rewrite the span. JSON only.",
                temperature=0.1,
            )
            parsed = parse_json_object(raw)
            action = parsed.get("action")
            conf = float(parsed.get("confidence") or 0)
            if action in {"keep", "drop"} and 0 <= conf <= 1:
                by_id[(span.start, span.end, span.kind)] = EditionSpan(
                    span.start,
                    span.end,
                    span.kind,
                    action,
                    max(span.confidence, conf) if action == span.action else conf,
                    f"{span.reason} (llm {action})",
                )
        except Exception:
            continue
    resolved = list(by_id.values())
    resolved.sort(key=lambda s: (s.start, s.end, s.kind))
    return resolved
