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
)
from .edition.read_edition_steps import (
    ReadEditionStepError,
    assemble_edition_from_package,
    load_structure,
    parse_micro_chapter,
    resolve_stripped_source,
    run_macro_step,
    section_source_slice,
)
from .edition.serialize import blocks_to_markdown
from .paths import corpus_root


def _map_error(exc: Exception) -> ValueError:
    if isinstance(exc, (ReadEditionError, ReadEditionStepError)):
        return ValueError(str(exc))
    raise exc


def get_status(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    return package_status(work_id, corpus=corpus)


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
) -> dict[str, Any]:
    try:
        return parse_micro_chapter(work_id, chapter_id, corpus=corpus, use_llm=use_llm)
    except ReadEditionStepError as exc:
        raise _map_error(exc) from exc


def parse_micro_batch(
    work_id: str,
    chapter_ids: list[str],
    *,
    corpus: Path | None = None,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for ch_id in chapter_ids:
        try:
            parsed[ch_id] = parse_micro_chapter(work_id, ch_id, corpus=corpus, use_llm=use_llm)
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
        chapter = {
            "chapter_id": chapter_id,
            "title": section.get("title"),
            "subtitle": section.get("subtitle"),
            "kind": section.get("kind"),
            "char_range": [section.get("start_char"), section.get("end_char")],
            "micro_status": "pending",
            "source_preview": section_source_slice(text, section)[:2000],
            "blocks": [],
            "reading_markdown": "",
        }
    qa = (load_qa_report(package_dir).get("chapters") or {}).get(chapter_id)
    overrides = load_overrides(package_dir).get(chapter_id)
    chapter["qa"] = qa
    chapter["overrides"] = overrides
    return chapter


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
