"""Two-step Read Edition: macro structure (step 1) + per-chapter micro parse (step 2)."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..catalog import get_work, is_hub_translation, resolve_content_path
from ..jsonfile import package_lock, write_json_atomic
from ..paths import corpus_root
from .hitl_ops import (
    HITL_KINDS,
    apply_auto_ok,
    apply_footnote_links,
    apply_quote_decisions,
    empty_job,
    extract_dump_notes,
    footnote_records_from_items,
    merge_item_decisions,
    scan_kind,
    summarize_items,
    wrap_overrides_from_items,
)
from .profile import detect_family
from .llm_defaults import default_use_llm_relabel
from .macro import attach_container_parents, build_macro_structure, section_source_slice
from .macro_review import apply_structure_edit, build_review, propose_toc_candidate
from .pipeline import build_edition
from .ref import build_read_edition
from .serialize import build_edition_document, blocks_to_markdown, detect_content_kind, edition_hash, split_hints_from_blocks
from .ref_schema import REF_PARSER_VERSION, validate_edition


class ReadEditionStepError(RuntimeError):
    pass


def package_root(work_id: str, content_hash: str, *, corpus: Path) -> Path:
    safe_id = work_id.replace("/", "_")
    safe_hash = content_hash.replace("/", "_")[:64]
    return corpus / "read-editions" / safe_id / safe_hash


def structure_path(package_dir: Path) -> Path:
    return package_dir / "structure.json"


def load_structure(package_dir: Path) -> dict[str, Any] | None:
    path = structure_path(package_dir)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_structure(package_dir: Path, structure: dict[str, Any]) -> None:
    package_dir.mkdir(parents=True, exist_ok=True)
    with package_lock(package_dir):
        write_json_atomic(structure_path(package_dir), structure)


def resolve_stripped_source(
    work_id: str,
    *,
    corpus: Path | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    from ..translation.assemble import assemble_finals

    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)
    if is_hub_translation(work):
        source_id = str(work.get("derived_from") or "")
        text, meta = assemble_finals(source_id, require_complete=True)
        return text, {"content_hash": meta["content_hash"], "origin": "hub_translation"}, work
    path = resolve_content_path(work, root=root)
    if not path.is_file():
        raise ReadEditionStepError(f"missing manuscript: {path}")
    if not work.get("content_hash"):
        raise ReadEditionStepError(f"{work_id} has no content_hash — run: knowledgehub hash")
    raw = path.read_text(encoding="utf-8", errors="replace")
    text, report = build_edition(
        raw,
        language=str(work.get("language") or "en"),
        work={**work, "_corpus_root": str(root)},
        strip_only=True,
    )
    family = report.get("family") or detect_family(raw, work=work, language=str(work.get("language") or "en"))
    return text, {"content_hash": work["content_hash"], "family": family, "origin": "source"}, work


def resolve_package_dir(
    work_id: str,
    *,
    corpus: Path | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Locate the read-edition package without stripping the manuscript when possible."""
    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)
    if is_hub_translation(work) or not work.get("content_hash"):
        _text, meta, work = resolve_stripped_source(work_id, corpus=root)
        return package_root(work_id, str(meta["content_hash"]), corpus=root), meta, work
    meta = {"content_hash": work["content_hash"], "origin": "catalog"}
    return package_root(work_id, str(work["content_hash"]), corpus=root), meta, work


def load_raw_source(work_id: str, *, corpus: Path | None = None) -> str:
    from ..translation.assemble import assemble_finals

    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)
    if is_hub_translation(work):
        source_id = str(work.get("derived_from") or "")
        text, _meta = assemble_finals(source_id, require_complete=True)
        return text
    path = resolve_content_path(work, root=root)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _manifest_chapter_rows(structure: dict[str, Any], existing: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    by_id = {row["chapter_id"]: row for row in (existing or {}).get("chapters") or [] if row.get("chapter_id")}
    sections = list(structure.get("sections") or [])
    attach_container_parents(sections)
    rows: list[dict[str, Any]] = []
    for sec in sections:
        sid = sec["section_id"]
        prev = by_id.get(sid) or {}
        new_range = [sec.get("start_char"), sec.get("end_char")]
        prev_range = prev.get("char_range")
        range_changed = prev_range is not None and prev_range != new_range
        parent_id = sec.get("parent_id")
        if range_changed:
            rows.append(
                {
                    "chapter_id": sid,
                    "title": sec.get("title"),
                    "subtitle": sec.get("subtitle"),
                    "kind": sec.get("kind"),
                    "parent_id": parent_id,
                    "char_range": new_range,
                    "word_count": sec.get("word_count"),
                    "micro_status": "pending",
                    "block_count": None,
                    "qa_status": "pending",
                    "confidence": sec.get("confidence"),
                }
            )
        else:
            rows.append(
                {
                    "chapter_id": sid,
                    "title": sec.get("title"),
                    "subtitle": sec.get("subtitle"),
                    "kind": sec.get("kind"),
                    "parent_id": parent_id,
                    "char_range": new_range,
                    "word_count": sec.get("word_count"),
                    "micro_status": prev.get("micro_status", "pending"),
                    "block_count": prev.get("block_count"),
                    "qa_status": prev.get("qa_status", "pending"),
                    "confidence": sec.get("confidence"),
                }
            )
    return rows


def _prune_stale_chapter_files(package_dir: Path, manifest: dict[str, Any]) -> None:
    """Drop chapter JSON when section is pending or no longer in manifest."""
    chapters_dir = package_dir / "chapters"
    if not chapters_dir.is_dir():
        return
    keep_complete: set[str] = set()
    for row in manifest.get("chapters") or []:
        ch_id = str(row.get("chapter_id") or "")
        if ch_id and row.get("micro_status") == "complete":
            ch_path = chapters_dir / f"{ch_id}.json"
            if ch_path.is_file():
                keep_complete.add(ch_id)
    for path in chapters_dir.glob("*.json"):
        if path.stem not in keep_complete:
            path.unlink(missing_ok=True)


def _sync_chapter_json_metadata(package_dir: Path, structure: dict[str, Any]) -> None:
    """Keep parsed chapter JSON kind/title in sync with structure (set_kind does not reparse)."""
    chapters_dir = package_dir / "chapters"
    if not chapters_dir.is_dir():
        return
    for sec in structure.get("sections") or []:
        sid = str(sec.get("section_id") or "")
        if not sid:
            continue
        path = chapters_dir / f"{sid}.json"
        if not path.is_file():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        kind = sec.get("kind")
        title = sec.get("title")
        subtitle = sec.get("subtitle")
        changed = False
        if kind is not None and doc.get("kind") != kind:
            doc["kind"] = kind
            changed = True
        if title is not None and doc.get("title") != title:
            doc["title"] = title
            changed = True
        if doc.get("subtitle") != subtitle:
            doc["subtitle"] = subtitle
            changed = True
        parent_id = sec.get("parent_id")
        if doc.get("parent_id") != parent_id:
            if parent_id:
                doc["parent_id"] = parent_id
            elif "parent_id" in doc:
                del doc["parent_id"]
            changed = True
        if changed:
            write_json_atomic(path, doc)


def remember_last_section(package_dir: Path, structure: dict[str, Any] | None, section_id: str | None) -> None:
    if not section_id:
        return
    with package_lock(package_dir):
        disk = load_structure(package_dir)
        target = disk if disk is not None else structure
        if not target:
            return
        hitl = dict(target.get("hitl") or {})
        if hitl.get("last_section_id") != section_id:
            hitl["last_section_id"] = section_id
            target["hitl"] = hitl
            save_structure(package_dir, target)
        if structure is not None:
            mirrored = dict(structure.get("hitl") or {})
            mirrored["last_section_id"] = section_id
            structure["hitl"] = mirrored


def persist_package_structure(
    work_id: str,
    structure: dict[str, Any],
    *,
    corpus: Path | None = None,
    reset_micro: bool = False,
) -> dict[str, Any]:
    """Write structure.json + manifest; optionally drop inherited micro status."""
    root = corpus or corpus_root()
    _text, meta, work = resolve_stripped_source(work_id, corpus=root)
    content_hash = str(meta["content_hash"])
    package_dir = package_root(work_id, content_hash, corpus=root)
    language = str(work.get("language") or structure.get("language") or "en")
    family = str(structure.get("source_family") or meta.get("family") or "plain")
    structure["work_id"] = work_id
    structure["content_hash"] = content_hash
    structure["source_family"] = family
    structure["language"] = language
    with package_lock(package_dir):
        save_structure(package_dir, structure)
        manifest_path = package_dir / "manifest.json"
        old_manifest: dict[str, Any] = {}
        if not reset_micro and manifest_path.is_file():
            old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = {
            "package_version": "2",
            "pipeline": "two_step",
            "work_id": work_id,
            "title": work.get("title"),
            "language": language,
            "content_hash": content_hash,
            "macro_status": "complete",
            "macro_mode": structure.get("mode"),
            "macro_model": structure.get("model"),
            "macro_summary_vi": structure.get("summary_vi"),
            "content_kind": structure.get("content_kind"),
            "source_family": family,
            "ref_parser_version": REF_PARSER_VERSION,
            "chapter_count": structure.get("section_count"),
            "chapters": _manifest_chapter_rows(structure, None if reset_micro else old_manifest),
            "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        }
        write_json_atomic(manifest_path, manifest)
        _prune_stale_chapter_files(package_dir, manifest)
        if not reset_micro:
            _sync_chapter_json_metadata(package_dir, structure)
        (package_dir / "chapters").mkdir(exist_ok=True)
        (package_dir / "qa").mkdir(exist_ok=True)
    return {
        "package_dir": str(package_dir.relative_to(root)),
        "structure": structure,
        "manifest": manifest,
    }


def run_macro_step(
    work_id: str,
    *,
    corpus: Path | None = None,
    use_llm: bool = True,
    force: bool = False,
    keep_toc: bool = False,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    text, meta, work = resolve_stripped_source(work_id, corpus=root)
    content_hash = str(meta["content_hash"])
    package_dir = package_root(work_id, content_hash, corpus=root)
    existing = load_structure(package_dir)

    saved_toc: dict[str, Any] | None = None
    toc_excerpt: str | None = None
    if keep_toc:
        if not existing:
            raise ReadEditionStepError("Run phân đoạn first, then confirm TOC")
        saved_toc = dict((existing.get("hitl") or {}).get("toc") or {})
        if saved_toc.get("status") not in {"yes", "no", "none"}:
            raise ReadEditionStepError("Confirm TOC before phân loại lại")
        if saved_toc.get("status") == "yes":
            toc_excerpt = str(saved_toc.get("excerpt") or "").strip()
        else:
            # Rejected / no TOC: remacro without falling back to auto-extract.
            toc_excerpt = ""
    elif not force:
        if existing and existing.get("ref_parser_version") == REF_PARSER_VERSION:
            manifest_path = package_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
            return {
                "built": False,
                "package_dir": str(package_dir.relative_to(root)),
                "structure": existing,
                "manifest": manifest,
            }

    language = str(work.get("language") or "en")
    family = str(meta.get("family") or detect_family(text, work=work, language=language))
    raw = load_raw_source(work_id, corpus=root)
    structure = build_macro_structure(
        text,
        language=language,
        family=family,
        work=work,
        use_llm=use_llm,
        raw=raw,
        toc_excerpt=toc_excerpt,
    )
    structure["work_id"] = work_id
    structure["content_hash"] = content_hash
    structure["source_family"] = family
    if saved_toc is not None:
        structure["hitl"] = {"toc": saved_toc, "confirmed_starts": []}
    else:
        toc = propose_toc_candidate(text, raw)
        structure["hitl"] = {"toc": toc, "confirmed_starts": []}
    persisted = persist_package_structure(work_id, structure, corpus=root, reset_micro=True)
    return {"built": True, **persisted}


def reset_read_edition_step(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    """Wipe the package back to empty — no remacro, no TOC proposal."""
    root = corpus or corpus_root()
    _text, meta, _work = resolve_stripped_source(work_id, corpus=root)
    package_dir = package_root(work_id, str(meta["content_hash"]), corpus=root)
    existed = package_dir.is_dir()
    if existed:
        shutil.rmtree(package_dir)
    parent = package_dir.parent
    if parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
    return {
        "reset": True,
        "work_id": work_id,
        "cleared": existed,
        "package_dir": None,
    }


def review_structure_step(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    root = corpus or corpus_root()
    text, meta, work = resolve_stripped_source(work_id, corpus=root)
    package_dir = package_root(work_id, str(meta["content_hash"]), corpus=root)
    structure = load_structure(package_dir)
    if not structure:
        raise ReadEditionStepError("Run macro step first (structure.json missing)")
    language = str(work.get("language") or structure.get("language") or "en")
    raw = load_raw_source(work_id, corpus=root)
    review = build_review(text, structure, raw=raw, language=language)
    hitl = dict(structure.get("hitl") or {})
    toc = dict(review.get("toc_candidate") or hitl.get("toc") or {})
    if (not (hitl.get("toc") or {}).get("excerpt")) and toc.get("excerpt"):
        hitl["toc"] = toc
        structure["hitl"] = hitl
        save_structure(package_dir, structure)
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
    return {
        "structure": structure,
        "manifest": manifest,
        **review,
        "hitl": hitl,
    }


def confirm_toc_step(
    work_id: str,
    status: str,
    *,
    excerpt: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    if status not in {"yes", "no", "none"}:
        raise ReadEditionStepError("toc status must be yes, no, or none")
    root = corpus or corpus_root()
    text, meta, _work = resolve_stripped_source(work_id, corpus=root)
    package_dir = package_root(work_id, str(meta["content_hash"]), corpus=root)
    structure = load_structure(package_dir)
    if not structure:
        raise ReadEditionStepError("Run macro step first (structure.json missing)")
    hitl = dict(structure.get("hitl") or {})
    raw = load_raw_source(work_id, corpus=root)
    toc = dict(hitl.get("toc") or propose_toc_candidate(text, raw))
    if excerpt is not None:
        cleaned = str(excerpt).replace("\r\n", "\n").replace("\r", "\n")[:12000].strip("\n")
        toc["excerpt"] = cleaned
        toc["line_count"] = len([ln for ln in cleaned.split("\n") if ln.strip()])
        proposed = propose_toc_candidate(text, raw)
        if cleaned.strip() != str(proposed.get("excerpt") or "").strip():
            toc["source"] = "curated"
        elif not toc.get("source") or toc.get("source") == "none":
            toc["source"] = "raw"
    toc["status"] = status
    hitl["toc"] = toc
    structure["hitl"] = hitl
    persisted = persist_package_structure(work_id, structure, corpus=root, reset_micro=False)
    review = review_structure_step(work_id, corpus=root)
    return {**persisted, **review}


def confirm_layout_step(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    """Curator asserts macro structure is final. Requires ready_to_parse; does not parse."""
    root = corpus or corpus_root()
    text, meta, work = resolve_stripped_source(work_id, corpus=root)
    package_dir = package_root(work_id, str(meta["content_hash"]), corpus=root)
    structure = load_structure(package_dir)
    if not structure:
        raise ReadEditionStepError("Run macro step first (structure.json missing)")
    language = str(work.get("language") or structure.get("language") or "en")
    raw = load_raw_source(work_id, corpus=root)
    review = build_review(text, structure, raw=raw, language=language)
    if not review["health"].get("ready_to_parse"):
        raise ReadEditionStepError(review["health"].get("not_ready_reason") or "Structure not ready")
    hitl = dict(structure.get("hitl") or {})
    hitl["layout_ok"] = True
    structure["hitl"] = hitl
    persisted = persist_package_structure(work_id, structure, corpus=root, reset_micro=False)
    review = review_structure_step(work_id, corpus=root)
    return {**persisted, **review}


def ensure_ready_to_parse(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    """Raise unless diagnostics are clean and curator stamped Cấu trúc OK."""
    review = review_structure_step(work_id, corpus=corpus)
    health = review.get("health") or {}
    if not health.get("can_parse"):
        raise ReadEditionStepError(
            health.get("parse_block_reason")
            or health.get("not_ready_reason")
            or "Confirm layout (Cấu trúc OK) before parse"
        )
    return review


def edit_structure_step(
    work_id: str,
    *,
    action: str,
    section_id: str,
    start_line: int | None = None,
    kind: str | None = None,
    use_llm: bool | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    text, meta, work = resolve_stripped_source(work_id, corpus=root)
    package_dir = package_root(work_id, str(meta["content_hash"]), corpus=root)
    structure = load_structure(package_dir)
    if not structure:
        raise ReadEditionStepError("Run macro step first (structure.json missing)")
    language = str(work.get("language") or structure.get("language") or "en")
    try:
        new_structure, focused_start = apply_structure_edit(
            text,
            structure,
            action=action,
            section_id=section_id,
            start_line=start_line,
            kind=kind,
            language=language,
            use_llm=False if use_llm is None else use_llm,
            family=str(structure.get("source_family") or "") or None,
        )
    except ValueError as exc:
        raise ReadEditionStepError(str(exc)) from exc
    reset_micro = action not in {"confirm", "set_kind"}
    persisted = persist_package_structure(
        work_id, new_structure, corpus=root, reset_micro=reset_micro
    )
    focused = next(
        (s for s in (new_structure.get("sections") or []) if int(s.get("start_line") or -1) == focused_start),
        None,
    )
    focused_id = (focused or {}).get("section_id")
    if focused_id:
        remember_last_section(package_dir, persisted.get("structure") or new_structure, focused_id)
    review = review_structure_step(work_id, corpus=root)
    return {
        **persisted,
        **review,
        "focused_section_id": focused_id,
        "focused_start_line": focused_start,
    }


def parse_micro_chapter(
    work_id: str,
    chapter_id: str,
    *,
    corpus: Path | None = None,
    use_llm: bool | None = None,
    require_ready: bool = True,
    hitl_scan: bool = False,
) -> dict[str, Any]:
    """Parse one chapter's REF. ``hitl_scan`` defaults off so reparse/tests skip a rescan; API and jobs pass True."""
    root = corpus or corpus_root()
    text, meta, work = resolve_stripped_source(work_id, corpus=root)
    content_hash = str(meta["content_hash"])
    package_dir = package_root(work_id, content_hash, corpus=root)
    structure = load_structure(package_dir)
    if not structure:
        raise ReadEditionStepError("Run macro step first (structure.json missing)")
    section = next((s for s in structure.get("sections") or [] if s["section_id"] == chapter_id), None)
    if not section:
        raise ReadEditionStepError(f"Unknown section: {chapter_id}")
    if require_ready:
        ensure_ready_to_parse(work_id, corpus=root)

    if hitl_scan:
        try:
            from .jobs import raise_if_stopped, report_progress
        except ImportError:

            def raise_if_stopped() -> None:
                return None

            def report_progress(_phase: str, _detail: str | None = None) -> None:
                return None

        labels = {"wrap": "nối dòng", "footnotes": "chú thích", "quotes": "trích dẫn"}
        for kind in HITL_KINDS:
            raise_if_stopped()
            report_progress("scan", f"Đang quét {labels.get(kind, kind)}…")
            scan_hitl_step(work_id, kind, chapter_id=chapter_id, scope="chapter", corpus=root)
        report_progress("parse", f"Đang parse REF {chapter_id}…")

    use_llm_resolved = default_use_llm_relabel() if use_llm is None else use_llm
    slice_text = section_source_slice(text, section)
    language = str(work.get("language") or "en")
    family = str(structure.get("source_family") or meta.get("family") or "plain")
    wrap_job = load_hitl_job(package_dir, "wrap")
    footnote_job = load_hitl_job(package_dir, "footnotes")
    quote_job = load_hitl_job(package_dir, "quotes")
    wrap_overrides = wrap_overrides_from_items(wrap_job.get("items") or [], chapter_id=chapter_id)
    edition, ref_report = build_read_edition(
        slice_text,
        family=family,
        language=language,
        use_llm=use_llm_resolved,
        work_id=work_id,
        wrap_overrides=wrap_overrides or None,
    )
    blocks = edition.get("blocks") or []
    footnote_records = footnote_records_from_items(footnote_job.get("items") or [], chapter_id=chapter_id)
    if footnote_records:
        apply_footnote_links(blocks, footnote_records)
    apply_quote_decisions(blocks, quote_job.get("items") or [], chapter_id=chapter_id)
    reading_markdown = blocks_to_markdown(blocks)
    hashed = edition_hash(blocks)
    chapter_doc = {
        "chapter_id": chapter_id,
        "title": section.get("title"),
        "subtitle": section.get("subtitle"),
        "kind": section.get("kind"),
        "char_range": [section.get("start_char"), section.get("end_char")],
        "blocks": blocks,
        "footnotes": footnote_records,
        "reading_markdown": reading_markdown,
        "edition_hash": hashed,
        "content_kind": detect_content_kind(blocks, family=family),
        "ref_mode": ref_report.get("ref_mode"),
        "llm_segments": ref_report.get("llm_segments") or [],
        "notes": edition.get("notes") or [],
        "block_count": len(blocks),
        "word_count": section.get("word_count"),
        "micro_status": "complete",
        "parsed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    chapters_dir = package_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    with package_lock(package_dir):
        write_json_atomic(chapters_dir / f"{chapter_id}.json", chapter_doc)
        manifest_path = package_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        for row in manifest.get("chapters") or []:
            if row.get("chapter_id") == chapter_id:
                row["micro_status"] = "complete"
                row["block_count"] = len(blocks)
                row["ref_mode"] = ref_report.get("ref_mode")
                row["edition_hash"] = hashed
        manifest["updated_at"] = chapter_doc.get("parsed_at") or manifest.get("updated_at")
        write_json_atomic(manifest_path, manifest)
        remember_last_section(package_dir, structure, chapter_id)
    return chapter_doc


def assemble_edition_from_package(
    package_dir: Path,
    *,
    language: str,
    source_family: str,
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ReadEditionStepError("manifest.json missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("pipeline") != "two_step":
        raise ReadEditionStepError("Not a two-step package")

    chapters = manifest.get("chapters") or []
    incomplete: list[str] = []
    missing_json: list[str] = []
    chapters_dir = package_dir / "chapters"
    for row in chapters:
        ch_id = str(row.get("chapter_id") or "")
        if row.get("micro_status") != "complete":
            incomplete.append(ch_id)
            continue
        ch_path = chapters_dir / f"{ch_id}.json"
        if not ch_path.is_file():
            missing_json.append(ch_id)

    if not allow_incomplete and (incomplete or missing_json):
        parts: list[str] = []
        if incomplete:
            sample = ", ".join(incomplete[:5])
            suffix = "…" if len(incomplete) > 5 else ""
            parts.append(f"{len(incomplete)} section(s) not parsed ({sample}{suffix})")
        if missing_json:
            sample = ", ".join(missing_json[:5])
            suffix = "…" if len(missing_json) > 5 else ""
            parts.append(f"{len(missing_json)} parsed section(s) missing chapter JSON ({sample}{suffix})")
        raise ReadEditionStepError(
            "Cannot publish incomplete edition — not every chapter is Ready. "
            "Parse all sections first. " + "; ".join(parts)
        )

    merged_blocks: list[dict[str, Any]] = []
    merged_notes: list[dict[str, Any]] = []
    chapter_docs: list[dict[str, Any]] = []
    for row in chapters:
        if row.get("micro_status") != "complete":
            continue
        ch_path = chapters_dir / f"{row['chapter_id']}.json"
        if not ch_path.is_file():
            continue
        ch = json.loads(ch_path.read_text(encoding="utf-8"))
        merged_blocks.extend(ch.get("blocks") or [])
        merged_notes.extend(ch.get("notes") or [])
        chapter_docs.append(ch)

    if not merged_blocks:
        raise ReadEditionStepError("No parsed chapters — run micro parse on all sections")

    edition = build_edition_document(
        merged_blocks,
        language=language,
        source_family=source_family,
    )
    edition["split_hints"] = split_hints_from_blocks(merged_blocks)
    if merged_notes:
        edition["notes"] = merged_notes
    edition["_chapters"] = chapter_docs
    if incomplete or missing_json:
        edition["incomplete"] = True
        edition["incomplete_sections"] = incomplete + missing_json
    errors = validate_edition(edition)
    if errors:
        raise ReadEditionStepError(f"assembled edition invalid: {'; '.join(errors[:3])}")
    return edition


def hitl_path(package_dir: Path, kind: str) -> Path:
    return package_dir / "hitl" / f"{kind}.json"


def scanned_chapter_ids(job: dict[str, Any]) -> list[str]:
    ids: set[str] = set()
    for cid in job.get("chapter_stats") or {}:
        if cid:
            ids.add(str(cid))
    for item in job.get("items") or []:
        cid = item.get("chapter_id")
        if cid:
            ids.add(str(cid))
    return sorted(ids)


def load_hitl_job(package_dir: Path, kind: str) -> dict[str, Any]:
    if kind not in HITL_KINDS:
        raise ReadEditionStepError(f"unknown HITL kind: {kind}")
    path = hitl_path(package_dir, kind)
    if not path.is_file():
        return empty_job(kind)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("kind", kind)
    data.setdefault("items", [])
    data.setdefault("chapter_stats", {})
    data.setdefault("summary", summarize_items(data.get("items") or []))
    data["scanned_chapter_ids"] = scanned_chapter_ids(data)
    return data


def save_hitl_job(package_dir: Path, kind: str, job: dict[str, Any]) -> dict[str, Any]:
    job["kind"] = kind
    job["updated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    job["summary"] = summarize_items(
        job.get("items") or [],
        extra={k: v for k, v in (job.get("summary") or {}).items() if k in {"auto_join", "auto_keep"}},
    )
    job["scanned_chapter_ids"] = scanned_chapter_ids(job)
    folder = package_dir / "hitl"
    folder.mkdir(parents=True, exist_ok=True)
    with package_lock(package_dir):
        write_json_atomic(hitl_path(package_dir, kind), job)
    return job


def _hitl_package(work_id: str, *, corpus: Path | None = None) -> tuple[Path, str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = corpus or corpus_root()
    text, meta, work = resolve_stripped_source(work_id, corpus=root)
    package_dir = package_root(work_id, str(meta["content_hash"]), corpus=root)
    structure = load_structure(package_dir)
    if not structure:
        raise ReadEditionStepError("Run macro step first (structure.json missing)")
    return package_dir, text, meta, work, structure


def hitl_overview_step(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    package_dir, _meta, _work = resolve_package_dir(work_id, corpus=corpus)
    if not load_structure(package_dir):
        raise ReadEditionStepError("Run macro step first (structure.json missing)")
    kinds = {}
    for kind in HITL_KINDS:
        job = load_hitl_job(package_dir, kind)
        kinds[kind] = {
            "kind": kind,
            "status": job.get("status") or "idle",
            "trial_chapter_id": job.get("trial_chapter_id"),
            "trial_confirmed": bool(job.get("trial_confirmed")),
            "scope": job.get("scope"),
            "summary": job.get("summary") or summarize_items(job.get("items") or []),
            "scanned_chapter_ids": scanned_chapter_ids(job),
            "updated_at": job.get("updated_at"),
        }
    return {"kinds": kinds}


def get_hitl_job_step(work_id: str, kind: str, *, corpus: Path | None = None) -> dict[str, Any]:
    if kind not in HITL_KINDS:
        raise ReadEditionStepError(f"unknown HITL kind: {kind}")
    package_dir, _meta, _work = resolve_package_dir(work_id, corpus=corpus)
    if not load_structure(package_dir):
        raise ReadEditionStepError("Run macro step first (structure.json missing)")
    return load_hitl_job(package_dir, kind)


def scan_hitl_step(
    work_id: str,
    kind: str,
    *,
    chapter_id: str | None = None,
    scope: str = "chapter",
    corpus: Path | None = None,
) -> dict[str, Any]:
    if kind not in HITL_KINDS:
        raise ReadEditionStepError(f"unknown HITL kind: {kind}")
    if scope not in {"chapter", "book"}:
        raise ReadEditionStepError("scope must be chapter or book")
    package_dir, text, meta, work, structure = _hitl_package(work_id, corpus=corpus)
    existing = load_hitl_job(package_dir, kind)
    if scope == "book" and not existing.get("trial_confirmed"):
        raise ReadEditionStepError("Xác nhận chương thử trước khi chạy toàn văn bản")
    family = str(structure.get("source_family") or meta.get("family") or "plain")
    language = str(work.get("language") or structure.get("language") or "en")
    sections = list(structure.get("sections") or [])
    if scope == "chapter":
        if not chapter_id:
            raise ReadEditionStepError("chapter_id required for trial scan")
        targets = [s for s in sections if s.get("section_id") == chapter_id]
        if not targets:
            raise ReadEditionStepError(f"Unknown section: {chapter_id}")
    else:
        targets = sections
        chapter_id = existing.get("trial_chapter_id") or chapter_id

    dump_notes = extract_dump_notes(text) if kind == "footnotes" else None
    wrap_job = load_hitl_job(package_dir, "wrap") if kind == "quotes" else None
    new_items: list[dict[str, Any]] = []
    extra_keys = ("auto_join", "auto_keep", "linked", "unmatched")
    chapter_stats: dict[str, Any] = {}
    from .jobs import raise_if_stopped, report_progress

    for index, section in enumerate(targets, 1):
        sid = str(section["section_id"])
        raise_if_stopped()
        report_progress("scan", f"Đang quét {kind} {index}/{len(targets)}…")
        slice_text = section_source_slice(text, section)
        wrap_overrides = None
        if wrap_job is not None:
            wrap_overrides = wrap_overrides_from_items(wrap_job.get("items") or [], chapter_id=sid) or None
        items, extra = scan_kind(
            kind,
            slice_text,
            chapter_id=sid,
            family=family,
            language=language,
            dump_notes=dump_notes,
            work_id=work_id,
            wrap_overrides=wrap_overrides,
            use_llm=False,
        )
        new_items.extend(items)
        chapter_stats[sid] = {key: int(extra.get(key) or 0) for key in extra_keys}

    with package_lock(package_dir):
        current = load_hitl_job(package_dir, kind)
        stats = dict(current.get("chapter_stats") or {})
        stats.update(chapter_stats)
        extra_acc = {
            key: sum(int((stats.get(cid) or {}).get(key) or 0) for cid in stats) for key in extra_keys
        }
        if scope == "chapter":
            sid = str(chapter_id)
            kept = [it for it in (current.get("items") or []) if str(it.get("chapter_id")) != sid]
            chapter_old = [it for it in (current.get("items") or []) if str(it.get("chapter_id")) == sid]
            merged = kept + apply_auto_ok(merge_item_decisions(chapter_old, new_items))
            if current.get("scope") == "book":
                job_scope = "book"
                job_status = current.get("status") or "book"
                job_confirmed = bool(current.get("trial_confirmed"))
                trial_id = current.get("trial_chapter_id") or chapter_id
            elif current.get("trial_confirmed"):
                job_scope = "chapter"
                job_status = "trial_confirmed"
                job_confirmed = True
                trial_id = current.get("trial_chapter_id") or chapter_id
            else:
                job_scope = "chapter"
                job_status = "trial"
                job_confirmed = False
                trial_id = chapter_id
        else:
            merged = apply_auto_ok(merge_item_decisions(current.get("items") or [], new_items))
            job_scope = "book"
            job_status = "book"
            job_confirmed = bool(current.get("trial_confirmed"))
            trial_id = current.get("trial_chapter_id") or chapter_id

        job = {
            "kind": kind,
            "status": job_status,
            "trial_chapter_id": trial_id,
            "trial_confirmed": job_confirmed,
            "scope": job_scope,
            "items": merged,
            "chapter_stats": stats,
            "summary": extra_acc,
        }
        return save_hitl_job(package_dir, kind, job)


def confirm_hitl_trial_step(
    work_id: str,
    kind: str,
    *,
    chapter_id: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    if kind not in HITL_KINDS:
        raise ReadEditionStepError(f"unknown HITL kind: {kind}")
    package_dir, _text, _meta, _work, _structure = _hitl_package(work_id, corpus=corpus)
    with package_lock(package_dir):
        job = load_hitl_job(package_dir, kind)
        trial_id = job.get("trial_chapter_id") or chapter_id
        if job.get("status") in {None, "idle"} or not trial_id:
            raise ReadEditionStepError("Chạy thử một chương trước khi xác nhận")
        job["trial_chapter_id"] = trial_id
        job["trial_confirmed"] = True
        if job.get("status") != "book":
            job["status"] = "trial_confirmed"
        return save_hitl_job(package_dir, kind, job)


def decide_hitl_step(
    work_id: str,
    kind: str,
    *,
    decision: str,
    item_ids: list[str] | None = None,
    suspects_only: bool = False,
    chapter_id: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    if kind not in HITL_KINDS:
        raise ReadEditionStepError(f"unknown HITL kind: {kind}")
    if decision not in {"accept", "reject", "clear"}:
        raise ReadEditionStepError("decision must be accept, reject, or clear")
    package_dir, _meta, _work = resolve_package_dir(work_id, corpus=corpus)
    if not load_structure(package_dir):
        raise ReadEditionStepError("Run macro step first (structure.json missing)")
    root = corpus or corpus_root()
    with package_lock(package_dir):
        job = load_hitl_job(package_dir, kind)
        wanted = set(item_ids or [])
        if not wanted and suspects_only and not chapter_id and job.get("scope") == "chapter":
            chapter_id = job.get("trial_chapter_id")
        changed = 0
        affected: set[str] = set()
        for item in job.get("items") or []:
            if wanted:
                if item.get("id") not in wanted:
                    continue
            else:
                if chapter_id and item.get("chapter_id") != chapter_id:
                    continue
                if suspects_only and not item.get("suspect"):
                    continue
                if not suspects_only:
                    continue
            if decision == "clear":
                item.pop("decision", None)
                item.pop("auto_ok", None)
            else:
                item["decision"] = decision
                if decision != "accept":
                    item.pop("auto_ok", None)
            changed += 1
            cid = str(item.get("chapter_id") or "")
            if cid:
                affected.add(cid)
        if changed == 0 and (wanted or suspects_only):
            raise ReadEditionStepError("Không khớp item nào")
        extra = {k: v for k, v in (job.get("summary") or {}).items() if k in {"auto_join", "auto_keep"}}
        job["summary"] = extra
        saved = save_hitl_job(package_dir, kind, job)
        affected_ids = sorted(affected)
    reparsed: list[str] = []
    apply_errors: list[str] = []
    for cid in affected_ids:
        chapter_path = package_dir / "chapters" / f"{cid}.json"
        if not chapter_path.is_file():
            continue
        try:
            parse_micro_chapter(
                work_id, cid, corpus=root, require_ready=False, use_llm=False, hitl_scan=False
            )
            reparsed.append(cid)
        except ReadEditionStepError as exc:
            apply_errors.append(f"{cid}: {exc}")
    if reparsed:
        saved["reparsed"] = reparsed
    if apply_errors:
        saved["apply_errors"] = apply_errors
    return saved

