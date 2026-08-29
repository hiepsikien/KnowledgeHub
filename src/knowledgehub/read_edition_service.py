"""HTTP-facing helpers for Read Edition CMS module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .edition.overrides import apply_block_patches, merge_block_patches
from .edition.read_edition import (
    ReadEditionError,
    build_read_edition_package,
    effective_edition,
    load_chapter,
    load_manifest,
    load_overrides,
    load_qa_report,
    package_status,
    qa_all_chapters,
    qa_read_edition_chapter,
    read_edition_dir,
    resolve_edition,
    save_overrides,
    split_edition_chapters,
)
from .edition.ref_schema import validate_edition
from .edition.serialize import blocks_to_markdown
from .paths import corpus_root


def _as_http_value_error(exc: ReadEditionError) -> ValueError:
    """Map ReadEditionError to ValueError so FastAPI routes return 400."""
    return ValueError(str(exc))


def get_status(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    return package_status(work_id, corpus=corpus)


def build_package(
    work_id: str,
    *,
    corpus: Path | None = None,
    force: bool = False,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    try:
        return build_read_edition_package(work_id, corpus=corpus, force=force, use_llm=use_llm)
    except ReadEditionError as exc:
        raise _as_http_value_error(exc) from exc


def get_manifest(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    try:
        root = corpus or corpus_root()
        status = package_status(work_id, corpus=root)
        if not status.get("ready"):
            raise ValueError(status.get("error") or "edition not ready")
        if not status.get("package_built"):
            build_read_edition_package(work_id, corpus=root)
            status = package_status(work_id, corpus=root)
        manifest = status.get("manifest")
        if not manifest:
            raise ValueError("manifest missing")
        return manifest
    except ReadEditionError as exc:
        raise _as_http_value_error(exc) from exc


def get_chapter(work_id: str, chapter_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    try:
        root = corpus or corpus_root()
        edition, _, _ = resolve_edition(work_id, corpus=root)
        build_read_edition_package(work_id, corpus=root)
        package_dir = read_edition_dir(work_id, str(edition["edition_hash"]), corpus=root)
        chapter = load_chapter(package_dir, chapter_id)
        qa = (load_qa_report(package_dir).get("chapters") or {}).get(chapter_id)
        overrides = load_overrides(package_dir).get(chapter_id)
        chapter["qa"] = qa
        chapter["overrides"] = overrides
        return chapter
    except ReadEditionError as exc:
        raise _as_http_value_error(exc) from exc


def patch_chapter(
    work_id: str,
    chapter_id: str,
    *,
    block_patches: list[dict[str, Any]],
    curator_note: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    try:
        root = corpus or corpus_root()
        edition, _, _ = resolve_edition(work_id, corpus=root)
        build_read_edition_package(work_id, corpus=root)
        package_dir = read_edition_dir(work_id, str(edition["edition_hash"]), corpus=root)
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
    except ReadEditionError as exc:
        raise _as_http_value_error(exc) from exc


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
        return qa_all_chapters(work_id, corpus=corpus, use_llm=use_llm)
    except ReadEditionError as exc:
        raise _as_http_value_error(exc) from exc


def edition_for_publish(work_id: str, *, corpus: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        root = corpus or corpus_root()
        edition, report, _ = resolve_edition(work_id, corpus=root)
        build_read_edition_package(work_id, corpus=root)
        package_dir = read_edition_dir(work_id, str(edition["edition_hash"]), corpus=root)
        specs = split_edition_chapters(edition)
        effective = effective_edition(edition, package_dir=package_dir, chapter_specs=specs)
        errors = validate_edition(effective)
        if errors:
            raise ValueError(f"REF validation failed after overrides: {'; '.join(errors[:3])}")
        manifest = load_manifest(package_dir)
        return effective, {
            "manifest": manifest,
            "report": report,
            "package_dir": str(package_dir.relative_to(root)),
        }
    except ReadEditionError as exc:
        raise _as_http_value_error(exc) from exc
