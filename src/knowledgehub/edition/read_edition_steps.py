"""Two-step Read Edition: macro structure (step 1) + per-chapter micro parse (step 2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..catalog import get_work, is_hub_translation, resolve_content_path
from ..paths import corpus_root
from .profile import detect_family
from .llm_defaults import default_use_llm_relabel
from .macro import build_macro_structure, section_source_slice
from .pipeline import build_edition
from .ref import build_read_edition
from .serialize import build_edition_document, blocks_to_markdown, split_hints_from_blocks
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
    structure_path(package_dir).write_text(
        json.dumps(structure, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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


def _manifest_chapter_rows(structure: dict[str, Any], existing: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    by_id = {row["chapter_id"]: row for row in (existing or {}).get("chapters") or [] if row.get("chapter_id")}
    rows: list[dict[str, Any]] = []
    for sec in structure.get("sections") or []:
        sid = sec["section_id"]
        prev = by_id.get(sid) or {}
        new_range = [sec.get("start_char"), sec.get("end_char")]
        prev_range = prev.get("char_range")
        range_changed = prev_range is not None and prev_range != new_range
        if range_changed:
            rows.append(
                {
                    "chapter_id": sid,
                    "title": sec.get("title"),
                    "subtitle": sec.get("subtitle"),
                    "kind": sec.get("kind"),
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


def run_macro_step(
    work_id: str,
    *,
    corpus: Path | None = None,
    use_llm: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    text, meta, work = resolve_stripped_source(work_id, corpus=root)
    content_hash = str(meta["content_hash"])
    package_dir = package_root(work_id, content_hash, corpus=root)

    if not force:
        existing = load_structure(package_dir)
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
    structure = build_macro_structure(
        text,
        language=language,
        family=family,
        work=work,
        use_llm=use_llm,
    )
    structure["work_id"] = work_id
    structure["content_hash"] = content_hash
    structure["source_family"] = family
    save_structure(package_dir, structure)

    manifest_path = package_dir / "manifest.json"
    old_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
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
        "chapters": _manifest_chapter_rows(structure, old_manifest),
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    (package_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _prune_stale_chapter_files(package_dir, manifest)
    (package_dir / "chapters").mkdir(exist_ok=True)
    (package_dir / "qa").mkdir(exist_ok=True)
    return {
        "built": True,
        "package_dir": str(package_dir.relative_to(root)),
        "structure": structure,
        "manifest": manifest,
    }


def parse_micro_chapter(
    work_id: str,
    chapter_id: str,
    *,
    corpus: Path | None = None,
    use_llm: bool | None = None,
) -> dict[str, Any]:
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

    use_llm_resolved = default_use_llm_relabel() if use_llm is None else use_llm
    slice_text = section_source_slice(text, section)
    language = str(work.get("language") or "en")
    family = str(structure.get("source_family") or meta.get("family") or "plain")
    edition, ref_report = build_read_edition(
        slice_text,
        family=family,
        language=language,
        use_llm=use_llm_resolved,
        work_id=work_id,
    )
    blocks = edition.get("blocks") or []
    chapter_doc = {
        "chapter_id": chapter_id,
        "title": section.get("title"),
        "subtitle": section.get("subtitle"),
        "kind": section.get("kind"),
        "char_range": [section.get("start_char"), section.get("end_char")],
        "blocks": blocks,
        "reading_markdown": edition.get("reading_markdown") or blocks_to_markdown(blocks),
        "edition_hash": edition.get("edition_hash"),
        "content_kind": edition.get("content_kind"),
        "ref_mode": ref_report.get("ref_mode"),
        "llm_segments": ref_report.get("llm_segments") or [],
        "block_count": len(blocks),
        "word_count": section.get("word_count"),
        "micro_status": "complete",
        "parsed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    chapters_dir = package_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    (chapters_dir / f"{chapter_id}.json").write_text(
        json.dumps(chapter_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    for row in manifest.get("chapters") or []:
        if row.get("chapter_id") == chapter_id:
            row["micro_status"] = "complete"
            row["block_count"] = len(blocks)
            row["ref_mode"] = ref_report.get("ref_mode")
            row["edition_hash"] = edition.get("edition_hash")
    manifest["updated_at"] = chapter_doc.get("parsed_at") or manifest.get("updated_at")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
            "Cannot publish incomplete edition — parse all sections first. " + "; ".join(parts)
        )

    merged_blocks: list[dict[str, Any]] = []
    for row in chapters:
        if row.get("micro_status") != "complete":
            continue
        ch_path = chapters_dir / f"{row['chapter_id']}.json"
        if not ch_path.is_file():
            continue
        ch = json.loads(ch_path.read_text(encoding="utf-8"))
        merged_blocks.extend(ch.get("blocks") or [])

    if not merged_blocks:
        raise ReadEditionStepError("No parsed chapters — run micro parse on all sections")

    edition = build_edition_document(
        merged_blocks,
        language=language,
        source_family=source_family,
    )
    edition["split_hints"] = split_hints_from_blocks(merged_blocks)
    if incomplete or missing_json:
        edition["incomplete"] = True
        edition["incomplete_sections"] = incomplete + missing_json
    errors = validate_edition(edition)
    if errors:
        raise ReadEditionStepError(f"assembled edition invalid: {'; '.join(errors[:3])}")
    return edition
