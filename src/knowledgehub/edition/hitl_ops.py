"""HITL scanners for wrap, footnotes, and quotes/emphasis — review, then apply."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .footnotes import parse_numbered_notes, split_footnotes_section
from .label_rules import (
    CONTINUATION_START,
    HANGING_WORD,
    HYPHEN_BREAK,
    _sentence_ended,
    _should_join,
)
from .lines import TextLine, iter_lines
from .llm_defaults import default_use_llm_relabel
from .ref import apply_wrap_overrides, blocks_from_labels, label_edition_lines, normalize_edition_source

HITL_KINDS = ("wrap", "footnotes", "quotes")

BODY_LINE = re.compile(r"^\[(\d{1,4})\]\s+(\S.*)$")
INLINE_MARKER = re.compile(r"\[(\d{1,4})\]")
ROMAN = re.compile(r"^[IVXLCDM]+$", re.I)

REASON_VI = {
    "blank_line": "có dòng trống giữa hai dòng",
    "capital_continue": "dòng sau viết hoa nhưng câu trước chưa hết",
    "hanging_word": "dòng trước kết bằng từ treo (the, of, và…)",
    "short_line": "dòng trước khá ngắn",
    "hyphen": "cắt giữa từ (gạch nối)",
    "possible_wrap": "câu chưa kết mà parser không ghép",
    "open_clause": "dở dấu phẩy / chấm phẩy",
    "continuation": "dòng sau giống phần tiếp của câu",
    "parser_disagree": "khác quyết định parser hiện tại",
    "unmatched_marker": "có marker nhưng chưa thấy nội dung chú thích",
    "unmatched_body": "có nội dung chú thích nhưng không thấy marker",
    "duplicate_marker": "cùng số xuất hiện nhiều lần trong chương",
    "duplicate_body": "trùng số nội dung chú thích",
    "short_body": "nội dung chú thích quá ngắn",
    "split_body": "nội dung chú thích bị ngắt nhiều dòng",
    "sequence_gap": "thiếu số trong dãy chú thích",
    "footnotes_dump_global": "nội dung lấy từ FOOTNOTES cuối sách — cần xác nhận đúng chương",
    "unclosed_quote": "thiếu dấu đóng ngoặc kép",
    "not_actionable": "chỉ ghi nhận; parse không đổi chỗ này",
    "short_blockquote": "blockquote rất ngắn — có thể là thoại thường",
    "unmatched_em": "gạch dưới lẻ, chưa thành cặp nhấn mạnh",
    "mixed_verse": "trộn thơ / văn xuôi trong cùng khối trích",
    "long_inline": "trích dẫn nội dòng rất dài",
}

_CLIP = 180


def empty_job(kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": "idle",
        "trial_chapter_id": None,
        "trial_confirmed": False,
        "scope": None,
        "items": [],
        "summary": _empty_summary(),
        "updated_at": None,
    }


def _empty_summary() -> dict[str, int]:
    return {
        "total": 0,
        "suspect": 0,
        "pending": 0,
        "accepted": 0,
        "rejected": 0,
        "auto_join": 0,
        "auto_keep": 0,
        "linked": 0,
        "unmatched": 0,
    }


def _norm_hitl_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower().rstrip("…. ")


def _snippet_hits(snippet: str, haystack: str) -> bool:
    needle = _norm_hitl_text(snippet)
    body = _norm_hitl_text(haystack)
    if not needle or not body:
        return False
    core = needle[:80] if len(needle) > 12 else needle
    return core in body or body in needle


def _quote_id_token(text: str) -> str:
    core = _norm_hitl_text(text)[:96]
    return hashlib.sha1(core.encode("utf-8")).hexdigest()[:12]


def _clip(text: str, n: int = _CLIP) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _glue(prev: str, nxt: str) -> str:
    if prev.rstrip().endswith("-") and nxt[:1].islower():
        return prev.rstrip()[:-1] + nxt.lstrip()
    return prev.rstrip() + " " + nxt.lstrip()


def _reasons_vi(reasons: list[str]) -> list[str]:
    return [REASON_VI.get(code, code) for code in reasons]


def _label_item(item: dict[str, Any]) -> dict[str, Any]:
    item["reason_labels"] = _reasons_vi(list(item.get("reasons") or []))
    return item


def summarize_items(items: list[dict[str, Any]], *, extra: dict[str, int] | None = None) -> dict[str, int]:
    summary = _empty_summary()
    if extra:
        summary.update(extra)
    summary["total"] = len(items)
    for item in items:
        if item.get("suspect"):
            summary["suspect"] += 1
        decision = item.get("decision")
        if decision == "accept":
            summary["accepted"] += 1
        elif decision == "reject":
            summary["rejected"] += 1
        elif item.get("suspect"):
            summary["pending"] += 1
        status = item.get("status")
        if status == "linked":
            summary["linked"] += 1
        elif status in {"unmatched_marker", "unmatched_body"}:
            summary["unmatched"] += 1
    return summary


def merge_item_decisions(old_items: list[dict[str, Any]], new_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prev = {row["id"]: row.get("decision") for row in old_items if row.get("id") and row.get("decision")}
    out: list[dict[str, Any]] = []
    for item in new_items:
        decision = prev.get(item["id"])
        if decision:
            item = {**item, "decision": decision}
        out.append(item)
    return out


def classify_wrap_pair(
    prev: str,
    nxt: str,
    *,
    family: str,
    blank_before: bool,
    parser_join: bool,
    prev_role: str = "prose",
    nxt_role: str = "prose",
) -> dict[str, Any]:
    """Decide join vs keep and whether a curator should look at the pair."""
    prev_r = prev.rstrip()
    nxt_s = nxt.strip()
    rule_join = _should_join(prev, nxt, family=family, blank_before=blank_before)
    high_hyphen = bool(HYPHEN_BREAK.search(prev_r) and nxt_s[:1].islower())
    hanging = bool(HANGING_WORD.search(prev_r) and not _sentence_ended(prev))
    ended = _sentence_ended(prev)
    reasons: list[str] = []

    if prev_role in {"heading", "hr", "metadata"} or nxt_role in {"heading", "hr", "metadata"}:
        proposed = "keep"
        suspect = False
        confidence = 0.96
    elif rule_join:
        proposed = "join"
        confidence = 0.88
        if blank_before:
            reasons.append("blank_line")
            confidence = 0.68
        if hanging and (blank_before or (nxt_s[:1].isupper() and not ended)):
            reasons.append("hanging_word")
        if nxt_s[:1].isupper() and not ended:
            reasons.append("capital_continue")
            confidence = min(confidence, 0.66)
        if len(prev_r) < 45 and not hanging and not high_hyphen:
            reasons.append("short_line")
            confidence = min(confidence, 0.7)
        if high_hyphen:
            reasons.append("hyphen")
            confidence = 0.95
            reasons[:] = [r for r in reasons if r == "hyphen"]
        suspect = bool(reasons) and not high_hyphen
        if hanging and not blank_before and nxt_s[:1].islower() and not high_hyphen:
            suspect = False
            confidence = 0.9
            reasons = [r for r in reasons if r not in {"hanging_word", "short_line"}]
            suspect = bool(reasons)
        if hanging and blank_before:
            suspect = True
            confidence = 0.7
    else:
        proposed = "keep"
        confidence = 0.9
        suspect = False
        if not ended and not blank_before and len(prev_r) >= 50:
            reasons.append("possible_wrap")
            suspect = True
            confidence = 0.55
            if CONTINUATION_START.match(nxt_s) or nxt_s[:1].islower():
                proposed = "join"
                reasons.append("continuation")
                confidence = 0.62
        elif prev_r.endswith((",", ";", "--", "—")) and not blank_before:
            reasons.append("open_clause")
            proposed = "join"
            suspect = True
            confidence = 0.6

    parser = "join" if parser_join else "keep"
    if parser != proposed:
        reasons.append("parser_disagree")
        suspect = True
        confidence = min(confidence, 0.6)

    return {
        "proposed": proposed,
        "parser": parser,
        "suspect": suspect,
        "reasons": reasons,
        "confidence": round(confidence, 2),
    }


def scan_wrap(
    text: str,
    *,
    chapter_id: str,
    family: str = "gutenberg",
    language: str = "en",
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    body, _apparatus, _unwrapped = normalize_edition_source(text, family=family, language=language)
    lines, labels, _events = label_edition_lines(body, family=family, language=language, use_llm=False)
    items: list[dict[str, Any]] = []
    auto_join = 0
    auto_keep = 0
    for i in range(len(lines) - 1):
        classified = classify_wrap_pair(
            lines[i].text,
            lines[i + 1].text,
            family=family,
            blank_before=lines[i + 1].blank_before,
            parser_join=bool(labels[i].join_next),
            prev_role=labels[i].role,
            nxt_role=labels[i + 1].role,
        )
        if not classified["suspect"]:
            if classified["proposed"] == "join":
                auto_join += 1
            else:
                auto_keep += 1
            continue
        preview = _glue(lines[i].text, lines[i + 1].text) if classified["proposed"] == "join" else ""
        items.append(
            _label_item(
                {
                    "id": f"wrap:{chapter_id}:{i}",
                    "chapter_id": chapter_id,
                    "kind": "wrap",
                    "line_index": i,
                    "next_index": i + 1,
                    "proposed": classified["proposed"],
                    "parser": classified["parser"],
                    "suspect": True,
                    "reasons": classified["reasons"],
                    "confidence": classified["confidence"],
                    "prev": _clip(lines[i].text),
                    "next": _clip(lines[i + 1].text),
                    "preview": _clip(preview, 240) if preview else "",
                    "blank_before": bool(lines[i + 1].blank_before),
                    "actionable": True,
                }
            )
        )
    extra = {"auto_join": auto_join, "auto_keep": auto_keep}
    return items, extra


def _anchor_near_marker(text: str, marker: str) -> str:
    pattern = re.compile(rf"([A-ZÀ-Ỵ][\wÀ-ỹ.'’\-]{{1,40}})\.?,?\s*{re.escape(marker)}")
    matches = list(pattern.finditer(text))
    for match in reversed(matches):
        name = match.group(1).strip(" .,'’")
        if len(name) >= 3 and not ROMAN.fullmatch(name):
            return name
    return ""


def _context_near_marker(text: str, marker: str) -> str:
    at = text.find(marker)
    if at < 0:
        return _clip(text, 160)
    lo = max(0, at - 70)
    hi = min(len(text), at + len(marker) + 70)
    return _clip(text[lo:hi], 180)


def _collect_indented_bodies(lines: list[TextLine]) -> dict[int, dict[str, Any]]:
    bodies: dict[int, dict[str, Any]] = {}
    i = 0
    n = len(lines)
    while i < n:
        match = BODY_LINE.match(lines[i].text)
        if match and (lines[i].indent >= 2 or (i > 0 and lines[i].blank_before)):
            number = int(match.group(1))
            parts = [match.group(2)]
            start = i
            i += 1
            while i < n and not BODY_LINE.match(lines[i].text):
                cont = lines[i]
                if cont.indent >= 2 or (not cont.blank_before and i == start + 1):
                    if _should_join(parts[-1], cont.text, family="gutenberg", blank_before=cont.blank_before) or cont.indent >= 2:
                        parts.append(cont.text)
                        i += 1
                        continue
                break
            body = re.sub(r"\s+", " ", " ".join(parts)).strip()
            if len(body) >= 4:
                bodies[number] = {
                    "number": number,
                    "body": body,
                    "source": "indented" if lines[start].indent >= 2 else "block",
                    "split": len(parts) > 2,
                    "line_index": start,
                }
            continue
        i += 1
    return bodies


def _dump_bodies(book_text: str | None) -> dict[int, str]:
    if not book_text:
        return {}
    _body, blob = split_footnotes_section(book_text)
    return parse_numbered_notes(blob) if blob else {}


def extract_dump_notes(book_text: str | None) -> dict[int, str]:
    return _dump_bodies(book_text)


def scan_footnotes(
    text: str,
    *,
    chapter_id: str,
    family: str = "gutenberg",
    language: str = "en",
    book_text: str | None = None,
    dump_notes: dict[int, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    del family, language
    body_text, _local_dump = split_footnotes_section(text)
    lines = iter_lines(body_text)
    local_bodies = _collect_indented_bodies(lines)
    dump = dump_notes if dump_notes is not None else _dump_bodies(book_text if book_text is not None else text)
    body_lines = {row["line_index"] for row in local_bodies.values()}

    markers: dict[int, list[dict[str, Any]]] = {}
    for row in lines:
        if row.index in body_lines:
            continue
        if BODY_LINE.match(row.text) and row.indent >= 2:
            continue
        for match in INLINE_MARKER.finditer(row.text):
            number = int(match.group(1))
            marker = match.group(0)
            markers.setdefault(number, []).append(
                {
                    "marker": marker,
                    "line_index": row.index,
                    "anchor": _anchor_near_marker(row.text, marker),
                    "context": _context_near_marker(row.text, marker),
                }
            )

    numbers = sorted(set(markers) | set(local_bodies))
    items: list[dict[str, Any]] = []
    for number in numbers:
        hits = markers.get(number) or []
        local = local_bodies.get(number)
        dumped = dump.get(number)
        marker = f"[{number}]"
        from_dump = bool(dumped) and not local
        body = (local or {}).get("body") or dumped or ""
        body_source = None
        if local:
            body_source = local.get("source")
        elif dumped:
            body_source = "footnotes_dump"
        reasons: list[str] = []
        status = "linked"
        if hits and body:
            status = "linked"
            if from_dump:
                reasons.append("footnotes_dump_global")
        elif hits and not body:
            status = "unmatched_marker"
            reasons.append("unmatched_marker")
        elif body and not hits:
            status = "unmatched_body"
            reasons.append("unmatched_body")
        if len(hits) > 1:
            reasons.append("duplicate_marker")
        if local and dumped and local.get("body") and dumped and local["body"][:40] != dumped[:40]:
            reasons.append("duplicate_body")
        if body and len(body) < 12:
            reasons.append("short_body")
        if local and local.get("split"):
            reasons.append("split_body")
        suspect = bool(reasons) or status != "linked"
        first = hits[0] if hits else {}
        items.append(
            _label_item(
                {
                    "id": f"fn:{chapter_id}:{number}",
                    "chapter_id": chapter_id,
                    "kind": "footnote",
                    "number": number,
                    "marker": marker,
                    "anchor": first.get("anchor") or "",
                    "context": first.get("context") or _clip(body, 160),
                    "body": body,
                    "body_source": body_source,
                    "marker_count": len(hits),
                    "status": status,
                    "suspect": suspect,
                    "reasons": reasons,
                    "line_index": first.get("line_index") if hits else (local or {}).get("line_index"),
                    "actionable": True,
                }
            )
        )
    if numbers:
        expected = set(range(min(numbers), max(numbers) + 1))
        missing = expected - set(numbers)
        if missing and len(missing) <= 8:
            for item in items:
                if item["number"] in {min(missing) - 1, min(missing) + 1, max(missing) - 1, max(missing) + 1}:
                    if "sequence_gap" not in item["reasons"]:
                        item["reasons"].append("sequence_gap")
                        item["suspect"] = True
                        item["reason_labels"] = _reasons_vi(item["reasons"])
    extra = {"linked": sum(1 for i in items if i["status"] == "linked"), "unmatched": sum(1 for i in items if i["status"] != "linked")}
    return items, extra


def _unclosed_quote_issues(text: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    straight = text.count('"')
    if straight % 2:
        at = text.rfind('"')
        snippet = _clip(text[max(0, at - 80) : at + 80], 160) if at >= 0 else _clip(text, 160)
        issues.append({"kind": "straight", "text": snippet, "reasons": ["unclosed_quote"]})
    if text.count("“") != text.count("”"):
        at = max(text.rfind("“"), text.rfind("”"))
        snippet = _clip(text[max(0, at - 80) : at + 80], 160) if at >= 0 else _clip(text, 160)
        issues.append({"kind": "curly", "text": snippet, "reasons": ["unclosed_quote"]})
    if text.count("«") != text.count("»"):
        issues.append({"kind": "guillemet", "text": _clip(text, 160), "reasons": ["unclosed_quote"]})
    return issues


def scan_quotes(
    text: str,
    *,
    chapter_id: str,
    family: str = "gutenberg",
    language: str = "en",
    work_id: str | None = None,
    wrap_overrides: dict[int, bool] | None = None,
    use_llm: bool | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    body, _apparatus, _unwrapped = normalize_edition_source(text, family=family, language=language)
    llm = default_use_llm_relabel() if use_llm is None else use_llm
    lines, labels, _events = label_edition_lines(
        body,
        family=family,
        language=language,
        use_llm=llm,
        wrap_overrides=wrap_overrides,
    )
    blocks, _profile = blocks_from_labels(lines, labels, work_id=work_id, language=language)
    items: list[dict[str, Any]] = []

    for bi, block in enumerate(blocks):
        kind = block.get("type")
        block_text = str(block.get("text") or "")
        if kind == "blockquote":
            reasons: list[str] = []
            if len(block_text) < 40:
                reasons.append("short_blockquote")
            stripped = block_text.strip()
            if "\n" in stripped and ('"' in stripped or "“" in stripped) and not stripped.endswith(('"', "”", "»", "_", ".", ",", "]")):
                reasons.append("mixed_verse")
            items.append(
                _label_item(
                    {
                        "id": f"q:{chapter_id}:blockquote:{_quote_id_token(block_text)}",
                        "chapter_id": chapter_id,
                        "kind": "quote",
                        "mark": "blockquote",
                        "block_index": bi,
                        "text": _clip(block_text, 280),
                        "context": "",
                        "suspect": bool(reasons),
                        "reasons": reasons,
                        "actionable": True,
                    }
                )
            )
        for span in block.get("spans") or []:
            style = span.get("style")
            if style not in {"quote", "em"}:
                continue
            span_text = str(span.get("text") or "")
            reasons = []
            if style == "em" and span_text.count("_") % 2:
                reasons.append("unmatched_em")
            if style == "quote" and len(span_text) > 280:
                reasons.append("long_inline")
            start = span.get("start")
            end = span.get("end")
            items.append(
                _label_item(
                    {
                        "id": f"q:{chapter_id}:{style}:{_quote_id_token(span_text)}",
                        "chapter_id": chapter_id,
                        "kind": "quote",
                        "mark": style,
                        "block_index": bi,
                        "start": start,
                        "end": end,
                        "text": _clip(span_text, 220),
                        "context": _clip(block_text, 180),
                        "suspect": bool(reasons),
                        "reasons": reasons,
                        "actionable": isinstance(start, int) and isinstance(end, int),
                    }
                )
            )

    odd_underscores = body.count("_") % 2 == 1
    if odd_underscores and not any("unmatched_em" in (it.get("reasons") or []) for it in items):
        items.append(
            _label_item(
                {
                    "id": f"q:{chapter_id}:em:unmatched",
                    "chapter_id": chapter_id,
                    "kind": "quote",
                    "mark": "em",
                    "text": _clip(body, 160),
                    "context": "",
                    "suspect": True,
                    "reasons": ["unmatched_em", "not_actionable"],
                    "actionable": False,
                }
            )
        )
    for i, issue in enumerate(_unclosed_quote_issues(body)):
        items.append(
            _label_item(
                {
                    "id": f"q:{chapter_id}:unclosed:{i}",
                    "chapter_id": chapter_id,
                    "kind": "quote",
                    "mark": "unclosed",
                    "text": issue["text"],
                    "context": "",
                    "suspect": True,
                    "reasons": issue["reasons"] + ["not_actionable"],
                    "actionable": False,
                }
            )
        )
    return items, {}


def scan_kind(
    kind: str,
    text: str,
    *,
    chapter_id: str,
    family: str = "gutenberg",
    language: str = "en",
    book_text: str | None = None,
    dump_notes: dict[int, str] | None = None,
    work_id: str | None = None,
    wrap_overrides: dict[int, bool] | None = None,
    use_llm: bool | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if kind == "wrap":
        return scan_wrap(text, chapter_id=chapter_id, family=family, language=language)
    if kind == "footnotes":
        return scan_footnotes(
            text,
            chapter_id=chapter_id,
            family=family,
            language=language,
            book_text=book_text,
            dump_notes=dump_notes,
        )
    if kind == "quotes":
        return scan_quotes(
            text,
            chapter_id=chapter_id,
            family=family,
            language=language,
            work_id=work_id,
            wrap_overrides=wrap_overrides,
            use_llm=use_llm,
        )
    raise ValueError(f"unknown HITL kind: {kind}")


def wrap_overrides_from_items(items: list[dict[str, Any]], *, chapter_id: str | None = None) -> dict[int, bool]:
    """Map line_index → join_next for decided wrap items in one chapter."""
    out: dict[int, bool] = {}
    for item in items:
        if item.get("kind") not in {None, "wrap"}:
            continue
        if chapter_id and item.get("chapter_id") != chapter_id:
            continue
        decision = item.get("decision")
        if decision not in {"accept", "reject"}:
            continue
        proposed_join = item.get("proposed") == "join"
        join = proposed_join if decision == "accept" else (not proposed_join)
        idx = item.get("line_index")
        if isinstance(idx, int):
            out[idx] = join
    return out


def footnote_records_from_items(
    items: list[dict[str, Any]],
    *,
    chapter_id: str | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in items:
        if chapter_id and item.get("chapter_id") != chapter_id:
            continue
        if item.get("decision") == "reject":
            continue
        auto = item.get("status") == "linked" and not item.get("suspect")
        if item.get("decision") != "accept" and not auto:
            continue
        records.append(
            {
                "marker": item.get("marker"),
                "number": item.get("number"),
                "anchor": item.get("anchor") or "",
                "body": item.get("body") or "",
                "status": item.get("status"),
                "chapter_id": item.get("chapter_id"),
            }
        )
    return records


def apply_footnote_links(blocks: list[dict[str, Any]], records: list[dict[str, Any]]) -> None:
    by_marker = {str(row.get("marker") or ""): row for row in records if row.get("marker")}
    if not by_marker:
        return
    for block in blocks:
        for span in block.get("spans") or []:
            if span.get("style") != "footnote":
                continue
            note = by_marker.get(str(span.get("text") or ""))
            if not note:
                continue
            if note.get("body"):
                span["note"] = note["body"]
            if note.get("anchor"):
                span["anchor"] = note["anchor"]


def _drop_matching_span(block: dict[str, Any], spec: dict[str, Any]) -> bool:
    style = spec.get("style")
    snippet = str(spec.get("text") or "")
    start = spec.get("start")
    end = spec.get("end")
    spans = list(block.get("spans") or [])
    kept: list[dict[str, Any]] = []
    dropped = False
    for span in spans:
        if span.get("style") != style:
            kept.append(span)
            continue
        same_text = _snippet_hits(snippet, str(span.get("text") or ""))
        same_range = (
            isinstance(start, int)
            and isinstance(end, int)
            and span.get("start") == start
            and span.get("end") == end
        )
        if same_text or (same_range and not snippet):
            dropped = True
            continue
        kept.append(span)
    if dropped:
        if kept:
            block["spans"] = kept
        else:
            block.pop("spans", None)
    return dropped


def apply_quote_decisions(blocks: list[dict[str, Any]], items: list[dict[str, Any]], *, chapter_id: str | None = None) -> None:
    """Apply reject decisions by snippet/span text so wrap/LLM reindex cannot hit the wrong block."""
    rejected_quotes: list[dict[str, Any]] = []
    for item in items:
        if chapter_id and item.get("chapter_id") != chapter_id:
            continue
        if item.get("decision") != "reject":
            continue
        rejected_quotes.append(item)

    claimed: set[int] = set()
    for item in rejected_quotes:
        if item.get("mark") != "blockquote":
            continue
        snippet = str(item.get("text") or "")
        matched: int | None = None
        for bi, block in enumerate(blocks):
            if bi in claimed or block.get("type") != "blockquote":
                continue
            if _snippet_hits(snippet, str(block.get("text") or "")):
                matched = bi
                break
        if matched is None:
            bi = item.get("block_index")
            if (
                isinstance(bi, int)
                and 0 <= bi < len(blocks)
                and bi not in claimed
                and blocks[bi].get("type") == "blockquote"
            ):
                matched = bi
        if matched is not None:
            blocks[matched]["type"] = "paragraph"
            claimed.add(matched)

    for item in rejected_quotes:
        if item.get("mark") not in {"quote", "em"}:
            continue
        spec = {
            "style": item.get("mark"),
            "text": item.get("text") or "",
            "start": item.get("start"),
            "end": item.get("end"),
        }
        bi = item.get("block_index")
        if isinstance(bi, int) and 0 <= bi < len(blocks) and _drop_matching_span(blocks[bi], spec):
            continue
        for block in blocks:
            if _drop_matching_span(block, spec):
                break
