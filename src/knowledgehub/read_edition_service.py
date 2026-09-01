"""HTTP-facing helpers for Read Edition CMS module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .edition.overrides import apply_block_patches, merge_block_patches
from .edition.read_edition import (
    ReadEditionError,
    load_chapter,
    load_manifest,
    load_overrides,
    load_qa_report,
    package_dir_for_work,
    package_status,
    qa_read_edition_chapter,
    save_overrides,
    list_read_edition_sessions,
)
from .edition.read_edition_steps import (
    ReadEditionStepError,
    remember_last_section,
    assemble_edition_from_package,
    confirm_hitl_trial_step,
    confirm_layout_step,
    confirm_toc_step,
    decide_hitl_step,
    edit_structure_step,
    ensure_ready_to_parse,
    get_hitl_job_step,
    hitl_overview_step,
    load_structure,
    parse_micro_chapter,
    resolve_stripped_source,
    review_structure_step,
    run_macro_step,
    scan_hitl_step,
    section_source_slice,
)
from .edition.serialize import blocks_to_markdown
from .paths import corpus_root

# Pending-section CMS preview: double the old 2000-char head-only cap.
SOURCE_PREVIEW_MAX = 4000
SOURCE_PREVIEW_HEAD = 2000
SOURCE_PREVIEW_TAIL = 2000


def head_tail_preview(
    text: str,
    *,
    max_chars: int = SOURCE_PREVIEW_MAX,
    head_chars: int = SOURCE_PREVIEW_HEAD,
    tail_chars: int = SOURCE_PREVIEW_TAIL,
) -> dict[str, Any]:
    """Head + tail excerpt; omit the middle when longer than max_chars."""
    body = text or ""
    n = len(body)
    if n <= max_chars:
        return {
            "source_preview": body,
            "source_preview_head": body,
            "source_preview_tail": "",
            "source_preview_truncated": False,
            "source_preview_omitted": 0,
        }
    head = body[:head_chars]
    tail = body[-tail_chars:]
    omitted = max(0, n - head_chars - tail_chars)
    marker = f"\n\n[… omitted {omitted} chars …]\n\n"
    return {
        "source_preview": f"{head}{marker}{tail}",
        "source_preview_head": head,
        "source_preview_tail": tail,
        "source_preview_truncated": True,
        "source_preview_omitted": omitted,
    }


def _map_error(exc: Exception) -> ValueError:
    if isinstance(exc, (ReadEditionError, ReadEditionStepError)):
        return ValueError(str(exc))
    raise exc


def get_status(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    return package_status(work_id, corpus=corpus)


def list_sessions(*, corpus: Path | None = None) -> list[dict[str, Any]]:
    return list_read_edition_sessions(corpus=corpus)


def run_macro(
    work_id: str,
    *,
    corpus: Path | None = None,
    force: bool = False,
    use_llm: bool = True,
) -> dict[str, Any]:
    try:
        return run_macro_step(work_id, corpus=corpus, force=force, use_llm=use_llm)
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def parse_micro(
    work_id: str,
    chapter_id: str,
    *,
    corpus: Path | None = None,
    use_llm: bool | None = None,
    require_ready: bool = True,
) -> dict[str, Any]:
    try:
        return parse_micro_chapter(
            work_id, chapter_id, corpus=corpus, use_llm=use_llm, require_ready=require_ready
        )
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def parse_micro_batch(
    work_id: str,
    chapter_ids: list[str],
    *,
    corpus: Path | None = None,
    use_llm: bool | None = None,
    require_ready: bool = True,
) -> dict[str, Any]:
    if require_ready:
        try:
            ensure_ready_to_parse(work_id, corpus=corpus)
        except ReadEditionStepError as exc:
            raise _map_error(exc) from exc
    parsed: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for ch_id in chapter_ids:
        try:
            parsed[ch_id] = parse_micro_chapter(
                work_id, ch_id, corpus=corpus, use_llm=use_llm, require_ready=False
            )
        except ReadEditionStepError as exc:
            errors[ch_id] = str(exc)
    return {"parsed": parsed, "errors": errors, "count": len(parsed)}


def get_manifest(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    root = corpus or corpus_root()
    status = package_status(work_id, corpus=root)
    if not status.get("ready"):
        raise ValueError(status.get("error") or "edition not ready")
    manifest = status.get("manifest")
    if not manifest:
        raise ValueError("Run macro step first — manifest missing")
    return manifest


def get_structure(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    try:
        root = corpus or corpus_root()
        package_dir, _, _ = package_dir_for_work(work_id, corpus=root)
        structure = load_structure(package_dir)
        if not structure:
            raise ValueError("structure.json missing — run macro step")
        return structure
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def get_review(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    try:
        return review_structure_step(work_id, corpus=corpus)
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def confirm_toc(
    work_id: str,
    status: str,
    *,
    excerpt: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    try:
        return confirm_toc_step(work_id, status, excerpt=excerpt, corpus=corpus)
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def confirm_layout(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    try:
        return confirm_layout_step(work_id, corpus=corpus)
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def edit_structure(
    work_id: str,
    *,
    action: str,
    section_id: str,
    start_line: int | None = None,
    kind: str | None = None,
    use_llm: bool | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    try:
        return edit_structure_step(
            work_id,
            action=action,
            section_id=section_id,
            start_line=start_line,
            kind=kind,
            use_llm=use_llm,
            corpus=corpus,
        )
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def get_chapter(work_id: str, chapter_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    try:
        return _get_chapter(work_id, chapter_id, corpus=corpus)
    except (ReadEditionError, ReadEditionStepError) as exc:
        raise _map_error(exc) from exc


def _get_chapter(work_id: str, chapter_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    root = corpus or corpus_root()
    package_dir, _, _ = package_dir_for_work(work_id, corpus=root)
    ch_path = package_dir / "chapters" / f"{chapter_id}.json"
    if ch_path.is_file():
        chapter = load_chapter(package_dir, chapter_id)
    else:
        structure = load_structure(package_dir)
        if not structure:
            raise ValueError("Chapter not parsed — run macro then micro parse")
        section = next((s for s in structure.get("sections") or [] if s["section_id"] == chapter_id), None)
        if not section:
            raise ValueError(f"Unknown chapter: {chapter_id}")
        text, _, _ = resolve_stripped_source(work_id, corpus=root)
        slice_text = section_source_slice(text, section)
        chapter = {
            "chapter_id": chapter_id,
            "title": section.get("title"),
            "subtitle": section.get("subtitle"),
            "kind": section.get("kind"),
            "parent_id": section.get("parent_id"),
            "char_range": [section.get("start_char"), section.get("end_char")],
            "micro_status": "pending",
            **head_tail_preview(slice_text),
            "blocks": [],
            "reading_markdown": "",
        }
        try:
            review = review_structure_step(work_id, corpus=root)
            diag = next(
                (row for row in review.get("sections") or [] if row.get("section_id") == chapter_id),
                None,
            )
            if diag:
                chapter["flags"] = diag.get("flags") or []
                chapter["inner_heads"] = diag.get("inner_heads") or []
                chapter["toc_match"] = diag.get("toc_match")
                chapter["compare"] = diag.get("compare") or {}
                chapter["confirmed"] = bool(diag.get("confirmed"))
                chapter["char_share"] = diag.get("char_share")
        except ReadEditionStepError:
            pass
    structure = load_structure(package_dir)
    if structure:
        section = next((s for s in structure.get("sections") or [] if s["section_id"] == chapter_id), None)
        if section:
            chapter["kind"] = section.get("kind", chapter.get("kind"))
            if section.get("parent_id"):
                chapter["parent_id"] = section.get("parent_id")
            elif "parent_id" in chapter:
                del chapter["parent_id"]
    qa = (load_qa_report(package_dir).get("chapters") or {}).get(chapter_id)
    overrides = load_overrides(package_dir).get(chapter_id)
    chapter["qa"] = qa
    chapter["overrides"] = overrides
    if "flags" not in chapter:
        try:
            review = review_structure_step(work_id, corpus=root)
            diag = next(
                (row for row in review.get("sections") or [] if row.get("section_id") == chapter_id),
                None,
            )
            if diag:
                chapter["flags"] = diag.get("flags") or []
                chapter["inner_heads"] = diag.get("inner_heads") or []
                chapter["toc_match"] = diag.get("toc_match")
                chapter["compare"] = diag.get("compare") or {}
                chapter["confirmed"] = bool(diag.get("confirmed"))
                chapter["char_share"] = diag.get("char_share")
        except ReadEditionStepError:
            pass
    if structure:
        remember_last_section(package_dir, structure, chapter_id)
    return chapter


def get_section_source(work_id: str, chapter_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    """Full stripped source for one macro section — not the truncated CMS preview."""
    try:
        return _get_section_source(work_id, chapter_id, corpus=corpus)
    except (ReadEditionError, ReadEditionStepError) as exc:
        raise _map_error(exc) from exc


def _get_section_source(work_id: str, chapter_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    root = corpus or corpus_root()
    package_dir, _, _ = package_dir_for_work(work_id, corpus=root)
    structure = load_structure(package_dir)
    if not structure:
        raise ValueError("Chapter not parsed — run macro then micro parse")
    section = next((s for s in structure.get("sections") or [] if s["section_id"] == chapter_id), None)
    if not section:
        raise ValueError(f"Unknown chapter: {chapter_id}")
    text, _, _ = resolve_stripped_source(work_id, corpus=root)
    slice_text = section_source_slice(text, section)
    return {
        "chapter_id": chapter_id,
        "title": section.get("title"),
        "kind": section.get("kind"),
        "char_range": [section.get("start_char"), section.get("end_char")],
        "chars": len(slice_text),
        "text": slice_text,
    }


def patch_chapter(
    work_id: str,
    chapter_id: str,
    *,
    block_patches: list[dict[str, Any]],
    curator_note: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    try:
        return _patch_chapter(
            work_id,
            chapter_id,
            block_patches=block_patches,
            curator_note=curator_note,
            corpus=corpus,
        )
    except (ReadEditionError, ReadEditionStepError) as exc:
        raise _map_error(exc) from exc


def _patch_chapter(
    work_id: str,
    chapter_id: str,
    *,
    block_patches: list[dict[str, Any]],
    curator_note: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    package_dir, _, _ = package_dir_for_work(work_id, corpus=root)
    chapter = load_chapter(package_dir, chapter_id)
    overrides = load_overrides(package_dir)
    entry = dict(overrides.get(chapter_id) or {})
    if block_patches:
        accumulated = merge_block_patches(entry.get("block_patches"), block_patches)
        patched = apply_block_patches(chapter["blocks"], block_patches)
        chapter["blocks"] = patched
        chapter["reading_markdown"] = blocks_to_markdown(patched)
        entry["block_patches"] = accumulated
    if curator_note is not None:
        entry["curator_note"] = curator_note
    entry["chapter_id"] = chapter_id
    overrides[chapter_id] = entry
    save_overrides(package_dir, overrides)
    (package_dir / "chapters" / f"{chapter_id}.json").write_text(
        json.dumps(chapter, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return chapter


def run_qa(
    work_id: str,
    *,
    chapter_id: str | None = None,
    use_llm: bool = True,
    corpus: Path | None = None,
) -> dict[str, Any]:
    try:
        if chapter_id:
            return qa_read_edition_chapter(work_id, chapter_id, corpus=corpus, use_llm=use_llm)
        raise ValueError("Specify chapter_id for QA in two-step pipeline")
    except (ReadEditionError, ReadEditionStepError) as exc:
        raise _map_error(exc) from exc


def edition_for_publish(work_id: str, *, corpus: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        root = corpus or corpus_root()
        package_dir, meta, work = package_dir_for_work(work_id, corpus=root)
        structure = load_structure(package_dir)
        if not structure:
            raise ValueError("Publish requires macro step — run phân đoạn (LLM) first")
        language = str(work.get("language") or "en")
        family = str(structure.get("source_family") or meta.get("family") or "plain")
        edition = assemble_edition_from_package(package_dir, language=language, source_family=family)
        manifest = load_manifest(package_dir)
        return edition, {
            "manifest": manifest,
            "structure": structure,
            "package_dir": str(package_dir.relative_to(root)),
            "pipeline": "two_step",
        }
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def get_hitl_overview(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    try:
        return hitl_overview_step(work_id, corpus=corpus)
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def get_hitl_job(work_id: str, kind: str, *, corpus: Path | None = None) -> dict[str, Any]:
    try:
        return get_hitl_job_step(work_id, kind, corpus=corpus)
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def scan_hitl(
    work_id: str,
    kind: str,
    *,
    chapter_id: str | None = None,
    scope: str = "chapter",
    corpus: Path | None = None,
) -> dict[str, Any]:
    try:
        return scan_hitl_step(
            work_id, kind, chapter_id=chapter_id, scope=scope, corpus=corpus
        )
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def confirm_hitl_trial(
    work_id: str,
    kind: str,
    *,
    chapter_id: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    try:
        return confirm_hitl_trial_step(work_id, kind, chapter_id=chapter_id, corpus=corpus)
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def decide_hitl(
    work_id: str,
    kind: str,
    *,
    decision: str,
    item_ids: list[str] | None = None,
    suspects_only: bool = False,
    chapter_id: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    try:
        return decide_hitl_step(
            work_id,
            kind,
            decision=decision,
            item_ids=item_ids,
            suspects_only=suspects_only,
            chapter_id=chapter_id,
            corpus=corpus,
        )
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc
