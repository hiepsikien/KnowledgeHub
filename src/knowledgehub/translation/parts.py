"""Split long chapters into paragraph-aligned parts for drafting."""

from __future__ import annotations

import json
import re
from typing import Any

from .segment import chapter_word_count

_MARKER = re.compile(r"\[\d+\]")
_HEADING_MAX_CHARS = 80


def _is_heading(line: str) -> bool:
    """A heading such as ``CHƯƠNG VII`` legitimately ends on a letter."""
    return bool(line) and len(line) <= _HEADING_MAX_CHARS and not any(c.islower() for c in line)


def looks_cut_off(text: str) -> bool:
    """True when the text stops mid-word instead of at a sentence boundary."""
    stripped = (text or "").rstrip()
    if len(stripped) < 20:
        return False
    last = stripped[-1]
    if not last.isalnum() or last.isdigit():
        return False
    return not _is_heading(stripped.rsplit("\n", 1)[-1].strip())


def translation_looks_truncated(source: str, output: str) -> bool:
    """True when an output breaks off mid-word somewhere its source did not.

    Source scans carry blank lines inside sentences, so a part can legitimately
    end on "…they do not". A faithful translation of that part ends mid-sentence
    as well, and must not be thrown away for matching the text it came from.
    Only a fallback anyway: the providers already reject any response whose
    finish reason says the model ran into its token ceiling.
    """
    return looks_cut_off(output) and not looks_cut_off(source)


def split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text or "") if part.strip()]


def pack_paragraphs(text: str, *, target: int = 1200, hard: int = 1500) -> list[str]:
    """Pack paragraphs into parts near `target` words, never splitting a paragraph.

    A single paragraph longer than `hard` becomes its own part.
    """
    target = max(1, int(target))
    hard = max(target, int(hard))
    paras = split_paragraphs(text)
    if not paras:
        stripped = (text or "").strip()
        return [stripped] if stripped else []
    parts: list[list[str]] = []
    current: list[str] = []
    words = 0
    for para in paras:
        count = chapter_word_count(para)
        if current and words + count > hard:
            parts.append(current)
            current, words = [para], count
            continue
        if current and words >= target:
            parts.append(current)
            current, words = [para], count
            continue
        current.append(para)
        words += count
    if current:
        parts.append(current)
    return ["\n\n".join(block) for block in parts]


def part_limits() -> tuple[int, int]:
    from ..settings import load_settings

    tr = load_settings().get("translation") or {}
    target = max(400, min(4000, int(tr.get("max_part_words") or 1200)))
    hard = max(target, min(5000, int(tr.get("hard_max_part_words") or 1500)))
    return target, hard


def marker_count(text: str) -> int:
    return len(_MARKER.findall(text or ""))


def _mode_raw(bucket: dict[str, Any] | None, mode: str) -> str:
    data = bucket if isinstance(bucket, dict) else {}
    if mode:
        return str(data.get(mode) or "").strip()
    return next((str(v).strip() for v in data.values() if str(v or "").strip()), "")


def _part_final(part: dict[str, Any], mode: str) -> str:
    text = str(part.get("final") or "").strip()
    if text:
        return text
    return _mode_raw(part.get("drafts") if isinstance(part.get("drafts"), dict) else None, mode)


def ensure_parts(
    segment: dict[str, Any],
    *,
    target: int | None = None,
    hard: int | None = None,
) -> list[dict[str, Any]]:
    if target is None or hard is None:
        target, hard = part_limits()
    source = str(segment.get("source_text") or "")
    packed = pack_paragraphs(source, target=target, hard=hard)
    if len(packed) <= 1:
        segment.pop("parts", None)
        return []
    existing = segment.get("parts") if isinstance(segment.get("parts"), list) else []
    by_source = {
        str(row.get("source_text") or ""): row for row in existing if isinstance(row, dict)
    }
    parts: list[dict[str, Any]] = []
    for index, text in enumerate(packed, start=1):
        prior = by_source.get(text)
        if prior is None and index - 1 < len(existing) and isinstance(existing[index - 1], dict):
            candidate = existing[index - 1]
            if str(candidate.get("source_text") or "") == text:
                prior = candidate
        row = dict(prior) if prior else {}
        row["id"] = index
        row["source_text"] = text
        row["words"] = chapter_word_count(text)
        parts.append(row)
    segment["parts"] = parts
    return parts


def join_parts(parts: list[dict[str, Any]], *, mode: str, field: str) -> str:
    chunks: list[str] = []
    for part in parts:
        if field == "final":
            chunk = _part_final(part, mode)
        else:
            chunk = _mode_raw(part.get(field) if isinstance(part.get(field), dict) else None, mode)
        if chunk:
            chunks.append(chunk)
    return "\n\n".join(chunks)


def previous_context(prev_en: str, prev_vi: str, *, paragraphs: int = 2) -> str:
    en = split_paragraphs(prev_en)[-paragraphs:]
    vi = split_paragraphs(prev_vi)[-paragraphs:]
    if not en or not vi:
        return ""
    return (
        "The previous part was already translated. Do not repeat it. "
        "Continue immediately after it.\n\n"
        "--- PREVIOUS SOURCE (do not translate) ---\n"
        + "\n\n".join(en)
        + "\n--- PREVIOUS TRANSLATION (do not repeat) ---\n"
        + "\n\n".join(vi)
        + "\n--- END PREVIOUS ---\n"
    )


def completeness_status(segment: dict[str, Any], *, mode: str = "") -> str:
    """ok | truncated | incomplete_parts | polish_pending | missing."""
    pipeline = segment.get("pipeline") if isinstance(segment.get("pipeline"), dict) else {}
    parts = segment.get("parts") if isinstance(segment.get("parts"), list) else []
    final = str(segment.get("final") or "").strip()
    source = str(segment.get("source_text") or "")
    raw = _mode_raw(segment.get("draft_raw") if isinstance(segment.get("draft_raw"), dict) else None, mode)
    if parts:
        missing_final = [p for p in parts if isinstance(p, dict) and not _part_final(p, mode)]
        cut_parts = [
            p
            for p in parts
            if isinstance(p, dict)
            and translation_looks_truncated(str(p.get("source_text") or ""), _part_final(p, mode))
        ]
        if missing_final:
            return "incomplete_parts"
        if cut_parts:
            return "truncated"
    if translation_looks_truncated(source, final):
        return "truncated"
    if final and abs(marker_count(source) - marker_count(final)) >= 2:
        return "truncated"
    if pipeline.get("polish_pending"):
        return "polish_pending"
    if final:
        return "ok"
    if raw:
        return "missing"
    return "missing"


def usable_final(segment: dict[str, Any], *, mode: str = "") -> bool:
    return completeness_status(segment, mode=mode) == "ok"


def prepare_chapter_for_resplit(segment: dict[str, Any], *, mode: str = "") -> dict[str, Any]:
    """Archive old translations and rebuild empty parts for a long/truncated chapter."""
    final = str(segment.get("final") or "").strip()
    raw = _mode_raw(segment.get("draft_raw") if isinstance(segment.get("draft_raw"), dict) else None, mode)
    if final and not segment.get("legacy_final"):
        segment["legacy_final"] = final
    if raw and not segment.get("legacy_draft_raw"):
        segment["legacy_draft_raw"] = raw
    segment["final"] = None
    segment["drafts"] = {"tight": None, "normal": None, "loose": None}
    segment["draft_raw"] = {}
    segment.pop("qa", None)
    segment["status"] = "pending"
    pipeline = dict(segment.get("pipeline") or {}) if isinstance(segment.get("pipeline"), dict) else {}
    pipeline["polish_pending"] = False
    pipeline.pop("completed_at", None)
    segment["pipeline"] = pipeline
    parts = ensure_parts(segment)
    for part in parts:
        part.pop("final", None)
        part["drafts"] = {}
        part["draft_raw"] = {}
        part.pop("pipeline", None)
    return segment


def split_long_chapters(source_work_id: str) -> dict[str, Any]:
    from .assemble import segment_files
    from .project import load_project
    from .segments_io import save_segment

    project = load_project(source_work_id)
    mode = str(project.get("translation_mode") or "")
    target, hard = part_limits()
    split: list[dict[str, Any]] = []
    for path in segment_files(source_work_id):
        payload = json.loads(path.read_text(encoding="utf-8"))
        words = int(payload.get("words") or chapter_word_count(str(payload.get("source_text") or "")))
        status = completeness_status(payload, mode=mode)
        packed = pack_paragraphs(str(payload.get("source_text") or ""), target=target, hard=hard)
        if len(packed) <= 1 and status != "truncated":
            continue
        prepare_chapter_for_resplit(payload, mode=mode)
        save_segment(path, payload)
        split.append(
            {
                "chapter": str(payload.get("chapter") or path.stem.removeprefix("ch").upper()),
                "words": words,
                "parts": len(payload.get("parts") or []),
                "completeness": completeness_status(payload, mode=mode),
            }
        )
    return {"work_id": source_work_id, "max_part_words": target, "chapters": split}
