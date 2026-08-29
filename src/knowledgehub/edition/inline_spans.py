from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

FOOTNOTE_INNER = re.compile(r"^\d{1,4}(?:,\s*\d{1,4})*$")
GUTENBERG_EM = re.compile(r"(?<![A-Za-z0-9])_([^_\n]+?)_(?![A-Za-z0-9])")
# Straight / curly double quotes used as inline quotation marks.
DQUOTE = re.compile(r'(?<!\w)"([^"\n]{2,}?)"(?!\w)|“([^”\n]{2,}?)”')
# Vietnamese / CJK corner quotes
CORNER_QUOTE = re.compile(r"「([^」\n]{2,}?)」|『([^』\n]{2,}?)』")
# Fullwidth parens common in Vietnamese editions
PAREN_PAIR = re.compile(r"\(([^)\n]{1,}?)\)|（([^）\n]{1,}?)）")
BRACKET_PAIR = re.compile(r"\[([^\]\n]{1,}?)\]")


@dataclass(frozen=True)
class InlineSpan:
    start: int
    end: int
    style: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "style": self.style, "text": self.text}


def _classify_bracket(inner: str) -> str:
    body = inner.strip()
    if FOOTNOTE_INNER.fullmatch(body):
        return "footnote"
    if len(body) >= 18 or body.count(" ") >= 3:
        return "bracket_note"
    if re.search(r"[A-Za-zÀ-ỹ]{4,}", body):
        return "bracket_note"
    if re.fullmatch(r"[A-Za-z]{1,3}\.?[A-Za-z0-9 .-]{0,40}", body):
        return "bracket_cite"
    return "bracket_other"


def _classify_paren(inner: str) -> str:
    body = inner.strip()
    if FOOTNOTE_INNER.fullmatch(body):
        return "footnote"
    if re.fullmatch(r"\d{1,4}", body):
        return "paren_page"
    lower = body.lower()
    if lower.startswith(("as ", "see ", "cf. ", "e.g. ", "i.e. ")):
        return "paren_cite"
    if body.count(" ") >= 5 or len(body) >= 40:
        return "paren_quote"
    if any(ch in body for ch in "\"'“”‘’"):
        return "paren_quote"
    # Short legal/latin labels: (Politics), (foedus aequum), (Digest 43.14.1.pr)
    if len(body.split()) <= 6 and re.search(r"[A-Za-zÀ-ỹ]", body):
        return "paren_cite"
    return "paren_aside"


def _add_span(spans: list[InlineSpan], start: int, end: int, style: str, text: str) -> None:
    if end <= start or not text.strip():
        return
    spans.append(InlineSpan(start=start, end=end, style=style, text=text))


def _scan_pattern(
    text: str,
    pattern: re.Pattern[str],
    *,
    classify,
    group_index: int = 1,
) -> list[InlineSpan]:
    spans: list[InlineSpan] = []
    for match in pattern.finditer(text):
        inner = match.group(group_index) or (match.group(2) if match.lastindex and match.lastindex >= 2 else "")
        if inner is None:
            continue
        style = classify(inner)
        _add_span(spans, match.start(), match.end(), style, match.group(0))
    return spans


def annotate_inline_spans(text: str) -> list[InlineSpan]:
    """Rule-only inline span detector. Does not rewrite text."""
    if not text or not text.strip():
        return []
    spans: list[InlineSpan] = []
    for match in GUTENBERG_EM.finditer(text):
        _add_span(spans, match.start(), match.end(), "em", match.group(0))
    for match in DQUOTE.finditer(text):
        inner = match.group(1) or match.group(2) or ""
        _add_span(spans, match.start(), match.end(), "quote", match.group(0))
    for match in CORNER_QUOTE.finditer(text):
        _add_span(spans, match.start(), match.end(), "quote", match.group(0))
    for match in BRACKET_PAIR.finditer(text):
        inner = match.group(1)
        _add_span(spans, match.start(), match.end(), _classify_bracket(inner), match.group(0))
    for match in PAREN_PAIR.finditer(text):
        inner = match.group(1) or match.group(2) or ""
        _add_span(spans, match.start(), match.end(), _classify_paren(inner), match.group(0))
    spans.sort(key=lambda s: (s.start, s.end))
    return _dedupe_overlaps(spans)


def _dedupe_overlaps(spans: list[InlineSpan]) -> list[InlineSpan]:
    if not spans:
        return []
    out = [spans[0]]
    for span in spans[1:]:
        prev = out[-1]
        if span.start < prev.end:
            # Keep the earlier span; drop the overlapping later one unless it is narrower footnote.
            if span.style == "footnote" and (prev.end - prev.start) > (span.end - span.start) + 8:
                out[-1] = span
            continue
        out.append(span)
    return out


def detect_quotation_profile(texts: Iterable[str]) -> dict[str, Any]:
    """Cheap corpus-level profile — no LLM."""
    counts: Counter[str] = Counter()
    for text in texts:
        for span in annotate_inline_spans(text):
            counts[span.style] += 1
    footnote = counts.get("footnote", 0)
    return {
        "footnote_style": "bracket" if footnote else "none",
        "footnote_count": footnote,
        "bracket_notes": counts.get("bracket_note", 0),
        "paren_cites": counts.get("paren_cite", 0),
        "paren_quotes": counts.get("paren_quote", 0),
        "paren_asides": counts.get("paren_aside", 0),
        "inline_quotes": counts.get("quote", 0),
        "italic_spans": counts.get("em", 0),
        "detector": "rule",
    }


def annotate_blocks(blocks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach spans[] to textual blocks; return profile from all paragraph text."""
    texts: list[str] = []
    out: list[dict[str, Any]] = []
    for block in blocks:
        row = dict(block)
        kind = row.get("type")
        if kind in {"paragraph", "blockquote", "heading", "verse_line"}:
            text = str(row.get("text") or "")
            if text:
                texts.append(text)
                spans = annotate_inline_spans(text)
                if spans:
                    row["spans"] = [s.to_dict() for s in spans]
        out.append(row)
    profile = detect_quotation_profile(texts)
    return out, profile
