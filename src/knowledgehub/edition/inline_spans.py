from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

FOOTNOTE_INNER = re.compile(r"^\d{1,4}(?:,\s*\d{1,4})*$")
GUTENBERG_EM = re.compile(r"(?<![A-Za-z0-9])_([^_\n]+?)_(?![A-Za-z0-9])")
FULL_LINE_EM = re.compile(r"^_([^_\n]+?)_$")
DQUOTE = re.compile(r'(?<!\w)"([^"\n]{2,}?)"(?!\w)|“([^”\n]{2,}?)”')
GUILLEMET = re.compile(r"«([^»\n]{2,}?)»")
CORNER_QUOTE = re.compile(r"「([^」\n]{2,}?)」|『([^』\n]{2,}?)』")
BRACKET_PAIR = re.compile(r"\[([^\]\n]{1,}?)\]")
YEAR_RANGE = re.compile(r"^\d{3,4}\s*[-–—]\s*\d{3,4}$")
VI_ERA = re.compile(r"^[A-Za-zÀ-ỹ\-]+\s+\d+\s*\(\d{3,4}(?:-\d{3,4})?\)$")


@dataclass(frozen=True)
class InlineSpan:
    start: int
    end: int
    style: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "style": self.style, "text": self.text}


def _iter_balanced(text: str, open_ch: str, close_ch: str) -> list[tuple[int, int, str]]:
    """Yield (start, end, inner) for balanced open/close pairs."""
    results: list[tuple[int, int, str]] = []
    i = 0
    n = len(text)
    open_full = {"(": ")", "（": "）"}
    close_full = {")", "）"}
    while i < n:
        if text[i] not in open_full and text[i] not in {"(", "（"}:
            i += 1
            continue
        start = i
        o = text[i]
        c = open_full.get(o, ")")
        depth = 0
        j = i
        while j < n:
            if text[j] == o:
                depth += 1
            elif text[j] == c:
                depth -= 1
                if depth == 0:
                    inner = text[start + 1 : j]
                    results.append((start, j + 1, inner))
                    i = j + 1
                    break
            j += 1
        else:
            i += 1
    return results


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
    if re.fullmatch(r"(19|20)\d{2}", body):
        return "paren_aside"
    if YEAR_RANGE.fullmatch(body):
        return "paren_aside"
    if VI_ERA.search(body):
        return "paren_cite"
    if re.fullmatch(r"\d{1,4}", body):
        if len(body) == 4 and int(body) >= 1000:
            return "paren_aside"
        return "paren_page"
    if FOOTNOTE_INNER.fullmatch(body):
        return "footnote"
    lower = body.lower()
    if lower.startswith(("as ", "see ", "cf. ", "e.g. ", "i.e. ")):
        return "paren_cite"
    if body.count(" ") >= 5 or len(body) >= 40:
        return "paren_aside"
    if any(ch in body for ch in "\"'“”‘’"):
        return "paren_quote"
    if len(body.split()) <= 6 and re.search(r"[A-Za-zÀ-ỹ]", body):
        return "paren_cite"
    return "paren_aside"


def _add_span(spans: list[InlineSpan], start: int, end: int, style: str, text: str) -> None:
    if end <= start or not text.strip():
        return
    spans.append(InlineSpan(start=start, end=end, style=style, text=text))


def _scan_em(text: str, spans: list[InlineSpan]) -> None:
    if FULL_LINE_EM.fullmatch(text.strip()):
        _add_span(spans, 0, len(text), "em", text.strip())
        return
    for match in GUTENBERG_EM.finditer(text):
        _add_span(spans, match.start(), match.end(), "em", match.group(0))


def annotate_inline_spans(text: str) -> list[InlineSpan]:
    """Rule-only inline span detector. Does not rewrite text."""
    if not text or not text.strip():
        return []
    spans: list[InlineSpan] = []
    _scan_em(text, spans)
    for match in DQUOTE.finditer(text):
        _add_span(spans, match.start(), match.end(), "quote", match.group(0))
    for match in GUILLEMET.finditer(text):
        _add_span(spans, match.start(), match.end(), "quote", match.group(0))
    for match in CORNER_QUOTE.finditer(text):
        _add_span(spans, match.start(), match.end(), "quote", match.group(0))
    for match in BRACKET_PAIR.finditer(text):
        inner = match.group(1)
        _add_span(spans, match.start(), match.end(), _classify_bracket(inner), match.group(0))
    for start, end, inner in _iter_balanced(text, "(", ")"):
        fullwidth_start = start > 0 and text[start] == "（"
        if fullwidth_start:
            continue
        _add_span(spans, start, end, _classify_paren(inner), text[start:end])
    for start, end, inner in _iter_balanced(text, "（", "）"):
        _add_span(spans, start, end, _classify_paren(inner), text[start:end])
    spans.sort(key=lambda s: (s.start, s.end))
    return _dedupe_overlaps(spans)


def _dedupe_overlaps(spans: list[InlineSpan]) -> list[InlineSpan]:
    if not spans:
        return []
    out = [spans[0]]
    for span in spans[1:]:
        prev = out[-1]
        if span.start < prev.end:
            if span.style == "footnote" and (prev.end - prev.start) > (span.end - span.start) + 8:
                out[-1] = span
            continue
        out.append(span)
    return out


def detect_quotation_profile(texts: Iterable[str]) -> dict[str, Any]:
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
        "list_markers": counts.get("list_marker", 0),
        "detector": "rule",
    }


_ANNOTATED_TYPES = frozenset(
    {
        "paragraph",
        "blockquote",
        "heading",
        "verse_line",
        "stanza",
        "dialogue",
        "stage_direction",
        "list_item",
        "metadata",
    }
)


def annotate_blocks(blocks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    texts: list[str] = []
    out: list[dict[str, Any]] = []
    for block in blocks:
        row = dict(block)
        kind = row.get("type")
        if kind in _ANNOTATED_TYPES:
            text = str(row.get("text") or "")
            if text:
                texts.append(text)
                span_list = annotate_inline_spans(text)
                if span_list:
                    row["spans"] = [s.to_dict() for s in span_list]
        out.append(row)
    profile = detect_quotation_profile(texts)
    return out, profile
