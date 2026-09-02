from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .cache import load_cached_edition, save_cached_edition
from .classify import classify_unsure_spans
from .detect import AOZORA_NOTE, AOZORA_RUBY, collect_spans
from .llm_defaults import default_use_llm_relabel
from .profile import detect_family
from .ref import build_read_edition
from .reflow import unwrap_hard_wrap
from .spans import DROP_MIN_CONFIDENCE, EditionSpan, apply_drops


def _strip_aozora_inline(text: str) -> str:
    return AOZORA_NOTE.sub("", AOZORA_RUBY.sub("", text.replace("｜", "")))


def _flags(spans: list[EditionSpan]) -> dict[str, bool]:
    dropped = {s.kind for s in spans if s.action == "drop" and s.confidence >= DROP_MIN_CONFIDENCE}
    kept_notes = any(s.kind == "notes" and s.action == "keep" for s in spans)
    return {
        "gutenberg": "wrapper" in dropped and any("Gutenberg" in s.reason for s in spans),
        "aozora": any(s.kind == "wrapper" and "Aozora" in s.reason for s in spans),
        "dropped_electronic_note": "electronic_note" in dropped,
        "dropped_produced_by": "produced_by" in dropped,
        "dropped_contents": "toc" in dropped,
        "dropped_tail_index": "index" in dropped,
        "dropped_transcriber": "transcriber" in dropped,
        "dropped_library_stamp": "library_stamp" in dropped,
        "dropped_publisher_ads": "ads" in dropped,
        "dropped_scan_boilerplate": "scan_boilerplate" in dropped,
        "kept_notes": kept_notes,
    }


def build_edition(
    text: str,
    *,
    language: str = "en",
    work: dict[str, Any] | None = None,
    use_llm: bool | None = None,
    preserve_toc: bool = False,
    strip_only: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Reading edition from a canonical manuscript. Does not rewrite the source file."""
    source_chars = len(text)
    family = detect_family(text, work=work, language=language)
    spans = collect_spans(text, family=family, work=work, preserve_toc=preserve_toc)
    use_llm_resolved = default_use_llm_relabel() if use_llm is None else use_llm
    if use_llm_resolved and not strip_only:
        spans = classify_unsure_spans(text, spans, enabled=True)
    body = apply_drops(text, spans)
    aozora_inline = False
    if family == "aozora":
        cleaned = _strip_aozora_inline(body)
        aozora_inline = cleaned != body
        body = cleaned
    unwrapped = False
    lang = (language or "en").lower()[:2]
    work_id = str((work or {}).get("id") or "")
    raw_hash = str((work or {}).get("content_hash") or "")
    corpus_hint = (work or {}).get("_corpus_root")
    edition: dict | None = None
    ref_report: dict = {}
    if strip_only:
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        if not body:
            raise ValueError("build_edition produced empty text")
        flags = _flags(spans)
        if aozora_inline:
            flags["aozora"] = True
        pg_wrapped = any(
            s.kind == "wrapper" and s.action == "drop" and "Gutenberg" in s.reason and s.confidence >= DROP_MIN_CONFIDENCE
            for s in spans
        )
        return body, {
            "source_chars": source_chars,
            "published_chars": len(body),
            "family": family,
            "edition_format": None,
            "edition_hash": None,
            "content_kind": None,
            "block_count": None,
            "ref": {},
            "edition": None,
            "gutenberg": pg_wrapped,
            "aozora": flags["aozora"],
            "dropped_electronic_note": flags["dropped_electronic_note"],
            "dropped_produced_by": flags["dropped_produced_by"],
            "dropped_contents": flags["dropped_contents"],
            "dropped_tail_index": flags["dropped_tail_index"],
            "dropped_transcriber": flags["dropped_transcriber"],
            "dropped_library_stamp": flags["dropped_library_stamp"],
            "dropped_publisher_ads": flags["dropped_publisher_ads"],
            "dropped_scan_boilerplate": flags["dropped_scan_boilerplate"],
            "kept_notes": flags["kept_notes"],
            "unwrapped": False,
            "unsure": [
                s.to_dict()
                for s in spans
                if s.action == "drop" and s.confidence < DROP_MIN_CONFIDENCE
            ],
            "spans": [s.to_dict() for s in spans],
        }
    if raw_hash and corpus_hint:
        edition = load_cached_edition(
            work_id,
            raw_hash,
            corpus=Path(str(corpus_hint)),
            llm_relabel=use_llm_resolved,
        )
    if edition is None:
        edition, ref_report = build_read_edition(
            body,
            family=family,
            language=language,
            use_llm=use_llm_resolved,
            work_id=work_id or None,
        )
        body = str(edition.get("reading_markdown") or body)
        unwrapped = bool(ref_report.get("unwrapped"))
        if raw_hash and corpus_hint:
            save_cached_edition(
                work_id,
                raw_hash,
                edition,
                corpus=Path(str(corpus_hint)),
                report=ref_report,
                llm_relabel=use_llm_resolved,
            )
    else:
        body = str(edition.get("reading_markdown") or body)
        unwrapped = True
        ref_report = {"ref_mode": "cache", "block_count": len(edition.get("blocks") or [])}
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if not body:
        raise ValueError("build_edition produced empty text")
    flags = _flags(spans)
    if aozora_inline:
        flags["aozora"] = True
    pg_wrapped = any(
        s.kind == "wrapper" and s.action == "drop" and "Gutenberg" in s.reason and s.confidence >= DROP_MIN_CONFIDENCE
        for s in spans
    )
    return body, {
        "source_chars": source_chars,
        "published_chars": len(body),
        "family": family,
        "edition_format": (edition or {}).get("edition_format"),
        "edition_hash": (edition or {}).get("edition_hash"),
        "content_kind": (edition or {}).get("content_kind"),
        "block_count": len((edition or {}).get("blocks") or []),
        "ref": ref_report,
        "edition": edition,
        "gutenberg": pg_wrapped,
        "aozora": flags["aozora"],
        "dropped_electronic_note": flags["dropped_electronic_note"],
        "dropped_produced_by": flags["dropped_produced_by"],
        "dropped_contents": flags["dropped_contents"],
        "dropped_tail_index": flags["dropped_tail_index"],
        "dropped_transcriber": flags["dropped_transcriber"],
        "dropped_library_stamp": flags["dropped_library_stamp"],
        "dropped_publisher_ads": flags["dropped_publisher_ads"],
        "dropped_scan_boilerplate": flags["dropped_scan_boilerplate"],
        "kept_notes": flags["kept_notes"],
        "unwrapped": unwrapped,
        "unsure": [
            s.to_dict()
            for s in spans
            if s.action == "drop" and s.confidence < DROP_MIN_CONFIDENCE
        ],
        "spans": [s.to_dict() for s in spans],
    }
