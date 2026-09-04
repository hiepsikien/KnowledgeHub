"""Align translation chapter segments with parsed REF chapters."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..catalog import get_work, resolve_content_path
from ..edition.profile import detect_family
from ..edition.read_edition import ReadEditionError, chapters_for_translation, parsed_chapter_source
from ..edition.ref import build_read_edition
from ..paths import corpus_root
from .paths import project_file, segments_dir
from .project import load_project
from .segment import chapter_word_count
from .titles import fallback_title_vi


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def ref_blocks_for_translation(blocks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """EN block graph for VI inherit: type/hidden/spans stay; only text is translated."""
    out: list[dict[str, Any]] = []
    for block in blocks or []:
        kind = str(block.get("type") or "paragraph")
        if kind == "hr":
            out.append({"block_id": block.get("block_id"), "type": "hr"})
            continue
        row: dict[str, Any] = {
            "block_id": block.get("block_id"),
            "type": kind,
            "hidden": bool(block.get("hidden")),
            "text": str(block.get("text") or ""),
        }
        if block.get("role"):
            row["role"] = block["role"]
        if block.get("lexical"):
            row["lexical"] = True
        if block.get("suppress_in_reader"):
            row["suppress_in_reader"] = True
        if block.get("spans"):
            row["spans"] = block["spans"]
        if block.get("speaker"):
            row["speaker"] = block["speaker"]
        if kind == "heading" and block.get("level") is not None:
            row["level"] = block["level"]
        out.append(row)
    return out


def inherit_translated_blocks(
    en_blocks: list[dict[str, Any]],
    translations: dict[str, str],
) -> list[dict[str, Any]]:
    """Copy EN type/hidden; replace text from ``translations[block_id]`` unless lexical."""
    out: list[dict[str, Any]] = []
    for block in ref_blocks_for_translation(en_blocks):
        bid = str(block.get("block_id") or "")
        if block.get("lexical"):
            out.append(block)
            continue
        if bid and bid in translations:
            row = dict(block)
            row["text"] = translations[bid]
            row.pop("spans", None)
            out.append(row)
            continue
        out.append(block)
    return out


def segment_is_approved(segment: dict[str, Any]) -> bool:
    return str(segment.get("status") or "") == "approved"


def source_text_kind(rows: list[dict[str, Any]]) -> str:
    kinds = {str(row.get("source_kind") or "raw_slice") for row in rows}
    if kinds == {"parsed"}:
        return "parsed"
    if kinds == {"raw_slice"}:
        return "raw_slice"
    return "mixed"


def segment_payload_from_ref_row(
    source_work_id: str,
    row: dict[str, Any],
    *,
    title_vi: str | None = None,
) -> dict[str, Any]:
    ch = str(row["chapter"])
    seg_id = f"ch{ch.lower()}"
    payload: dict[str, Any] = {
        "id": f"{source_work_id}--{seg_id}",
        "chapter": ch,
        "source_order": int(row.get("source_order") or 0),
    }
    if row.get("ref_chapter_id"):
        payload["ref_chapter_id"] = row["ref_chapter_id"]
    payload.update(
        {
            "words": row["words"],
            "source_text": row["text"],
            "source_text_kind": row.get("source_kind") or "raw_slice",
            "drafts": {"tight": None, "normal": None, "loose": None},
            "final": None,
            "status": "pending",
        }
    )
    if row.get("title"):
        payload["ref_title"] = row["title"]
    blocks = row.get("blocks") or []
    if blocks:
        payload["ref_blocks"] = ref_blocks_for_translation(blocks)
    heading = str(row.get("title") or ch)
    payload["title_vi"] = (title_vi or "").strip() or fallback_title_vi(heading)
    return payload


def _index_existing(
    seg_dir: Path,
) -> tuple[dict[str, tuple[dict[str, Any], Path]], list[Path]]:
    by_key: dict[str, tuple[dict[str, Any], Path]] = {}
    paths: list[Path] = []
    for path in sorted(seg_dir.glob("ch*.json")):
        if "-sample" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        paths.append(path)
        ref_id = str(data.get("ref_chapter_id") or "").strip()
        chapter = str(data.get("chapter") or "").strip().lower()
        if ref_id:
            by_key[f"ref:{ref_id}"] = (data, path)
        if chapter:
            by_key[f"ch:{chapter}"] = (data, path)
    return by_key, paths


def _match_existing(
    row: dict[str, Any], by_key: dict[str, tuple[dict[str, Any], Path]]
) -> tuple[dict[str, Any], Path] | None:
    ref_id = str(row.get("ref_chapter_id") or "").strip()
    chapter = str(row.get("chapter") or "").strip().lower()
    if ref_id and f"ref:{ref_id}" in by_key:
        return by_key[f"ref:{ref_id}"]
    if chapter and f"ch:{chapter}" in by_key:
        return by_key[f"ch:{chapter}"]
    return None


def sync_translation_chapters_from_ref(
    source_work_id: str,
    *,
    overwrite: bool = False,
    include_front_matter: bool = False,
    keep_approved: bool = True,
    enqueue: bool = False,
    corpus: Path | None = None,
) -> dict[str, Any]:
    """Rewrite segment source_text from parsed REF chapters (opt-in)."""
    root = corpus or corpus_root()
    proj_path = project_file(source_work_id)
    if not proj_path.is_file():
        raise FileNotFoundError(f"No translation project for {source_work_id}")

    try:
        ref_chapters = chapters_for_translation(
            source_work_id,
            corpus=root,
            include_front_matter=include_front_matter,
        )
    except ReadEditionError as exc:
        existing = sorted(
            p for p in segments_dir(source_work_id).glob("ch*.json") if "-sample" not in p.name
        )
        if existing:
            if not overwrite:
                raise FileExistsError(
                    f"{len(existing)} segment files exist — pass overwrite=True to replace from REF chapters"
                ) from exc
            return reparse_existing_segment_sources(
                source_work_id,
                keep_approved=keep_approved,
                enqueue=enqueue,
                corpus=root,
            )
        raise ValueError(str(exc)) from exc

    if not include_front_matter:
        ref_chapters = [c for c in ref_chapters if c.get("ref_chapter_id") != "ch-000-front"]

    seg_dir = segments_dir(source_work_id)
    existing = sorted(p for p in seg_dir.glob("ch*.json") if "-sample" not in p.name)
    if existing and not overwrite:
        raise FileExistsError(
            f"{len(existing)} segment files exist — pass overwrite=True to replace from REF chapters"
        )

    by_key, old_paths = _index_existing(seg_dir)
    written: list[str] = []
    kept: list[str] = []
    rewritten: list[str] = []
    keep_paths: set[Path] = set()
    consumed: set[Path] = set()

    for index, row in enumerate(ref_chapters):
        row = {**row, "source_order": index}
        ch = str(row["chapter"])
        seg_id = f"ch{ch.lower()}"
        seg_path = seg_dir / f"{seg_id}.json"
        matched = _match_existing(row, by_key)
        old = matched[0] if matched else None
        old_path = matched[1] if matched else None
        if keep_approved and old and segment_is_approved(old):
            payload = dict(old)
            payload["chapter"] = ch
            payload["id"] = f"{source_work_id}--{seg_id}"
            payload["source_order"] = index
            if row.get("ref_chapter_id"):
                payload["ref_chapter_id"] = row["ref_chapter_id"]
            if row.get("title"):
                payload["ref_title"] = row["title"]
            seg_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            kept.append(seg_id)
            keep_paths.add(seg_path)
            if old_path is not None and old_path != seg_path:
                consumed.add(old_path)
        else:
            title_vi = str((old or {}).get("title_vi") or "").strip() or None
            payload = segment_payload_from_ref_row(source_work_id, row, title_vi=title_vi)
            seg_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            rewritten.append(seg_id)
            keep_paths.add(seg_path)
            if old_path is not None and old_path != seg_path:
                consumed.add(old_path)
        written.append(seg_id)

    for path in old_paths:
        if path in keep_paths:
            continue
        if path in consumed:
            path.unlink()
            continue
        try:
            leftover = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            leftover = {}
        if keep_approved and segment_is_approved(leftover):
            kept.append(path.stem)
            continue
        path.unlink()

    kind = source_text_kind(ref_chapters)
    project = load_project(source_work_id)
    project["chapter_source"] = "ref"
    project["source_text_kind"] = kind
    project["segments_total"] = len(written)
    project["source"]["chapters"] = len(written)
    project["source"]["words"] = sum(int(c["words"]) for c in ref_chapters)
    project["updated_at"] = _now()
    project_file(source_work_id).write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result: dict[str, Any] = {
        "source_work_id": source_work_id,
        "segments_written": len(written),
        "segment_ids": written,
        "chapter_source": "ref",
        "source_text_kind": kind,
        "kept_approved": kept,
        "rewritten": rewritten,
        "parsed": sum(1 for row in ref_chapters if row.get("source_kind") == "parsed"),
        "raw_slice": sum(1 for row in ref_chapters if row.get("source_kind") != "parsed"),
    }
    if enqueue and rewritten:
        from .jobs import enqueue_missing_drafts

        result["enqueue"] = enqueue_missing_drafts(source_work_id)
    return result


def reparse_existing_segment_sources(
    source_work_id: str,
    *,
    keep_approved: bool = True,
    enqueue: bool = False,
    corpus: Path | None = None,
) -> dict[str, Any]:
    """Parse each existing chapter slice through REF matchers when no package exists."""
    root = corpus or corpus_root()
    work = get_work(source_work_id, corpus=root)
    language = str(work.get("language") or "en")
    sample = ""
    try:
        raw_path = resolve_content_path(work, root=root)
        if raw_path.is_file():
            sample = raw_path.read_text(encoding="utf-8", errors="replace")[:80000]
    except (ValueError, OSError):
        sample = ""
    family = detect_family(sample, work=work, language=language)
    if str(work.get("gutenberg_id") or "").strip() and family == "plain":
        family = "gutenberg"
    seg_dir = segments_dir(source_work_id)
    kept: list[str] = []
    rewritten: list[str] = []
    words = 0
    for path in sorted(p for p in seg_dir.glob("ch*.json") if "-sample" not in p.name):
        segment = json.loads(path.read_text(encoding="utf-8"))
        stem = path.stem
        if keep_approved and segment_is_approved(segment):
            kept.append(stem)
            words += int(segment.get("words") or 0)
            continue
        source = str(segment.get("source_text") or "")
        edition, _report = build_read_edition(
            source,
            family=family,
            language=language,
            use_llm=False,
            work_id=source_work_id,
            chapter_id=str(segment.get("ref_chapter_id") or stem),
            chapter_title=str(segment.get("ref_title") or segment.get("chapter") or ""),
        )
        text, blocks = parsed_chapter_source(edition)
        segment["source_text"] = text
        segment["source_text_kind"] = "parsed"
        segment["words"] = chapter_word_count(text)
        segment["ref_blocks"] = ref_blocks_for_translation(blocks)
        segment["drafts"] = {"tight": None, "normal": None, "loose": None}
        segment["final"] = None
        segment["status"] = "pending"
        segment.pop("draft_raw", None)
        segment.pop("parts", None)
        segment.pop("qa", None)
        segment.pop("pipeline", None)
        path.write_text(json.dumps(segment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rewritten.append(stem)
        words += int(segment["words"])

    project = load_project(source_work_id)
    project["chapter_source"] = project.get("chapter_source") or "ref"
    project["source_text_kind"] = "parsed"
    project["source"]["words"] = words
    project["source"]["chapters"] = len(kept) + len(rewritten)
    project["segments_total"] = len(kept) + len(rewritten)
    project["updated_at"] = _now()
    project_file(source_work_id).write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result: dict[str, Any] = {
        "source_work_id": source_work_id,
        "segments_written": len(kept) + len(rewritten),
        "segment_ids": kept + rewritten,
        "chapter_source": project["chapter_source"],
        "source_text_kind": "parsed",
        "kept_approved": kept,
        "rewritten": rewritten,
        "parsed": len(rewritten),
        "raw_slice": 0,
        "via": "reparse_existing",
    }
    if enqueue and rewritten:
        from .jobs import enqueue_missing_drafts

        result["enqueue"] = enqueue_missing_drafts(source_work_id)
    return result
