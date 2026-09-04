"""Build, load, and QA per-chapter Read Edition (REF/1) packages on disk."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..catalog import get_work, is_hub_translation, resolve_content_path
from ..jsonfile import package_lock, write_json_atomic
from ..paths import corpus_root
from .cache import load_cached_edition, save_cached_edition
from .footnotes import notes_for_chapter_blocks
from .llm_defaults import default_use_llm_relabel, gemini_available
from .overrides import apply_chapter_overrides, overrides_digest
from .ref import build_read_edition
from .ref_schema import REF_PARSER_VERSION, validate_edition
from .serialize import blocks_to_markdown, translation_source_from_blocks
from .toc import trim_trailing_wrap_toc
from .ref_qa import qa_read_edition
from .read_edition_steps import (
    ReadEditionStepError,
    assemble_edition_from_package,
    load_structure,
    package_root,
    resolve_package_dir,
    resolve_stripped_source,
    section_source_slice,
)

READ_EDITION_PACKAGE_VERSION = "2"


class ReadEditionError(RuntimeError):
    pass


def package_dir_for_work(
    work_id: str,
    *,
    corpus: Path | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    return resolve_package_dir(work_id, corpus=corpus)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def read_edition_dir(work_id: str, edition_hash: str, *, corpus: Path) -> Path:
    safe_id = work_id.replace("/", "_")
    safe_hash = edition_hash.replace("/", "_")[:64]
    return corpus / "read-editions" / safe_id / safe_hash


def split_edition_chapters(edition: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = edition.get("blocks") or []
    hints = edition.get("split_hints") or []
    if not blocks:
        return []
    if not hints:
        return [
            {
                "chapter_id": "ch-001",
                "title": "Full text",
                "block_start": 0,
                "block_end": len(blocks) - 1,
                "split_hint": None,
            }
        ]

    chapters: list[dict[str, Any]] = []
    first_start = int(hints[0]["block_index"])
    if first_start > 0:
        chapters.append(
            {
                "chapter_id": "ch-000-front",
                "title": "Front matter",
                "block_start": 0,
                "block_end": first_start - 1,
                "split_hint": None,
            }
        )

    for index, hint in enumerate(hints):
        start = int(hint["block_index"])
        end = (
            int(hints[index + 1]["block_index"]) - 1
            if index + 1 < len(hints)
            else len(blocks) - 1
        )
        title = str(hint.get("text") or f"Section {index + 1}").strip()
        chapters.append(
            {
                "chapter_id": f"ch-{len(chapters):03d}",
                "title": title,
                "block_start": start,
                "block_end": end,
                "split_hint": hint,
            }
        )
    return chapters


def chapter_document(edition: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    blocks = (edition.get("blocks") or [])[spec["block_start"] : spec["block_end"] + 1]
    md = blocks_to_markdown(blocks)
    return {
        "chapter_id": spec["chapter_id"],
        "title": spec["title"],
        "block_start": spec["block_start"],
        "block_end": spec["block_end"],
        "blocks": blocks,
        "notes": notes_for_chapter_blocks(blocks, edition.get("notes") or []),
        "reading_markdown": md,
        "split_hint": spec.get("split_hint"),
        "word_count": _word_count(md),
        "block_count": len(blocks),
    }


def _work_for_normalize(work: dict[str, Any], corpus: Path) -> dict[str, Any]:
    enriched = dict(work)
    enriched["_corpus_root"] = str(corpus)
    return enriched


def resolve_edition(
    work_id: str,
    *,
    corpus: Path | None = None,
    use_llm: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Build or load REF/1 edition for a catalog work. Returns (edition, report, stripped_source)."""
    from ..normalize import normalize_manuscript
    from ..translation.assemble import assemble_finals

    use_llm_resolved = default_use_llm_relabel() if use_llm is None else use_llm
    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)

    if is_hub_translation(work):
        source_id = str(work.get("derived_from") or "")
        text, meta = assemble_finals(source_id, require_complete=True)
        content_hash = str(meta["content_hash"])
        cached = load_cached_edition(work_id, content_hash, corpus=root, llm_relabel=use_llm_resolved)
        if cached:
            edition = cached
            report = {"ref_mode": "cache", "origin": "hub_translation", "chapters": meta["chapters"]}
        else:
            edition, ref_report = build_read_edition(
                text,
                family="plain",
                language=str(work.get("language") or "vi"),
                work_id=work_id,
                use_llm=use_llm_resolved,
            )
            save_cached_edition(
                work_id,
                content_hash,
                edition,
                corpus=root,
                report=ref_report,
                llm_relabel=use_llm_resolved,
            )
            report = {"ref": ref_report, "origin": "hub_translation", "chapters": meta["chapters"]}
        report["content_hash"] = content_hash
        return edition, report, text

    path = resolve_content_path(work, root=root)
    if not path.is_file():
        raise ReadEditionError(f"missing manuscript: {path}")
    if not work.get("content_hash"):
        raise ReadEditionError(f"{work_id} has no content_hash — run: knowledgehub hash")
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        _text, report = normalize_manuscript(
            raw,
            language=str(work.get("language") or "en"),
            work=_work_for_normalize(work, root),
            use_llm=use_llm_resolved,
        )
    except ValueError as exc:
        raise ReadEditionError(str(exc)) from exc
    edition = report.get("edition")
    if not edition:
        raise ReadEditionError(f"{work_id}: REF edition missing after normalize")
    from .pipeline import build_edition

    stripped_only, _ = build_edition(
        raw,
        language=str(work.get("language") or "en"),
        work=_work_for_normalize(work, root),
        strip_only=True,
    )
    report["content_hash"] = work.get("content_hash")
    return edition, report, stripped_only


def load_manifest(package_dir: Path) -> dict[str, Any] | None:
    path = package_dir / "manifest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_chapter(package_dir: Path, chapter_id: str) -> dict[str, Any]:
    path = package_dir / "chapters" / f"{chapter_id}.json"
    if not path.is_file():
        raise ReadEditionError(f"chapter not found: {chapter_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_overrides(package_dir: Path) -> dict[str, Any]:
    path = package_dir / "qa" / "overrides.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(data.get("chapters") or {})


def save_overrides(package_dir: Path, chapters: dict[str, Any]) -> dict[str, Any]:
    qa_dir = package_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": _now(), "chapters": chapters}
    with package_lock(package_dir):
        write_json_atomic(qa_dir / "overrides.json", payload)
        manifest_path = package_dir / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["overrides_hash"] = overrides_digest(chapters)
            manifest["updated_at"] = payload["updated_at"]
            write_json_atomic(manifest_path, manifest)
    return payload


def load_qa_report(package_dir: Path) -> dict[str, Any]:
    path = package_dir / "qa" / "report.json"
    if not path.is_file():
        return {"chapters": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"chapters": {}}


def save_qa_chapter(package_dir: Path, chapter_id: str, qa: dict[str, Any]) -> dict[str, Any]:
    qa_dir = package_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    report_path = qa_dir / "report.json"
    with package_lock(package_dir):
        report = load_qa_report(package_dir)
        chapters = dict(report.get("chapters") or {})
        chapters[chapter_id] = qa
        report["chapters"] = chapters
        report["updated_at"] = _now()
        write_json_atomic(report_path, report)

        manifest_path = package_dir / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for row in manifest.get("chapters") or []:
                if row.get("chapter_id") == chapter_id:
                    row["qa_status"] = "pass" if qa.get("passed") else "fail"
                    llm = qa.get("llm") or {}
                    if llm.get("verdict"):
                        row["qa_verdict"] = llm["verdict"]
            manifest["qa_updated_at"] = report["updated_at"]
            write_json_atomic(manifest_path, manifest)
    return report


def effective_edition(
    edition: dict[str, Any],
    *,
    package_dir: Path | None = None,
    chapter_specs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not package_dir or not package_dir.is_dir():
        return edition
    overrides = load_overrides(package_dir)
    if not overrides:
        return edition
    specs = chapter_specs or split_edition_chapters(edition)
    return apply_chapter_overrides(edition, overrides, chapter_specs=list(specs))


def build_read_edition_package(
    work_id: str,
    *,
    corpus: Path | None = None,
    force: bool = False,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)
    use_llm_resolved = default_use_llm_relabel() if use_llm is None else use_llm
    edition, report, _source = resolve_edition(work_id, corpus=root, use_llm=use_llm_resolved)
    errors = validate_edition(edition)
    if errors:
        raise ReadEditionError(f"REF validation failed: {'; '.join(errors[:5])}")

    edition_hash = str(edition["edition_hash"])
    package_dir = read_edition_dir(work_id, edition_hash, corpus=root)
    if package_dir.is_dir() and not force:
        manifest = load_manifest(package_dir)
        if manifest and manifest.get("ref_parser_version") == REF_PARSER_VERSION:
            return {
                "built": False,
                "package_dir": str(package_dir.relative_to(root)),
                "manifest": manifest,
                "report": report,
            }

    specs = split_edition_chapters(edition)
    package_dir.mkdir(parents=True, exist_ok=True)
    chapters_dir = package_dir / "chapters"
    chapters_dir.mkdir(exist_ok=True)
    (package_dir / "qa").mkdir(exist_ok=True)

    chapter_rows: list[dict[str, Any]] = []
    for spec in specs:
        ch = chapter_document(edition, spec)
        (chapters_dir / f"{spec['chapter_id']}.json").write_text(
            json.dumps(ch, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        chapter_rows.append(
            {
                "chapter_id": spec["chapter_id"],
                "title": spec["title"],
                "block_range": [spec["block_start"], spec["block_end"]],
                "word_count": ch["word_count"],
                "block_count": ch["block_count"],
                "qa_status": "pending",
            }
        )

    pipeline = "hub_translation" if is_hub_translation(work) else "same_language"
    manifest = {
        "package_version": READ_EDITION_PACKAGE_VERSION,
        "edition_format": edition.get("edition_format"),
        "work_id": work_id,
        "title": work.get("title"),
        "language": edition.get("language") or work.get("language") or "en",
        "pipeline": pipeline,
        "edition_hash": edition_hash,
        "content_hash": report.get("content_hash") or work.get("content_hash"),
        "content_kind": edition.get("content_kind"),
        "source_family": edition.get("source_family"),
        "block_count": len(edition.get("blocks") or []),
        "chapter_count": len(chapter_rows),
        "chapters": chapter_rows,
        "quotation_profile": edition.get("quotation_profile") or {},
        "ref_parser_version": REF_PARSER_VERSION,
        "ref_mode": (report.get("ref") or {}).get("ref_mode") or report.get("ref_mode") or "rule",
        "llm_relabel": use_llm_resolved,
        "llm_segment_count": len((report.get("ref") or {}).get("llm_segments") or []),
        "created_at": _now(),
        "updated_at": _now(),
    }
    (package_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (package_dir / "edition.full.json").write_text(
        json.dumps(edition, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md = str(edition.get("reading_markdown") or "")
    if md:
        (package_dir / "reading.md").write_text(md + "\n", encoding="utf-8")

    return {
        "built": True,
        "package_dir": str(package_dir.relative_to(root)),
        "manifest": manifest,
        "report": report,
        "validation_errors": [],
    }


def _read_edition_phase(
    structure: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> str:
    chapters = (manifest or {}).get("chapters") or []
    parsed = sum(1 for row in chapters if row.get("micro_status") == "complete")
    total = len(chapters) or len((structure or {}).get("sections") or [])
    hitl = dict((structure or {}).get("hitl") or {})
    toc_status = (hitl.get("toc") or {}).get("status")
    layout_ok = bool(hitl.get("layout_ok"))
    if not structure:
        return "empty"
    if total and parsed >= total:
        return "parsed"
    if parsed > 0:
        return "parsing"
    if layout_ok:
        return "layout_ok"
    if toc_status:
        return "hitl"
    return "macro"


def package_status(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)
    try:
        package_dir, meta, _work = resolve_package_dir(work_id, corpus=root)
    except ReadEditionStepError as exc:
        return {"work_id": work_id, "ready": False, "error": str(exc)}
    structure = load_structure(package_dir)
    manifest = load_manifest(package_dir) if (package_dir / "manifest.json").is_file() else None
    chapters = (manifest or {}).get("chapters") or []
    parsed = sum(1 for row in chapters if row.get("micro_status") == "complete")
    total = len(chapters) or len((structure or {}).get("sections") or [])
    hitl = dict((structure or {}).get("hitl") or {})
    toc_status = (hitl.get("toc") or {}).get("status")
    layout_ok = bool(hitl.get("layout_ok"))
    phase = _read_edition_phase(structure, manifest)
    return {
        "work_id": work_id,
        "title": work.get("title"),
        "language": work.get("language"),
        "ready": True,
        "publishable": structure is not None and total > 0 and parsed == total,
        "pipeline": "two_step" if structure else "legacy",
        "content_hash": meta.get("content_hash"),
        "macro_complete": structure is not None,
        "macro_mode": (structure or {}).get("mode"),
        "structure": structure,
        "manifest": manifest,
        "package_built": manifest is not None,
        "package_dir": str(package_dir.relative_to(root)) if package_dir.is_dir() else None,
        "chapters_total": len(chapters) or len((structure or {}).get("sections") or []),
        "chapters_parsed": parsed,
        "gemini_available": gemini_available(),
        "default_use_llm_relabel": default_use_llm_relabel(),
        "hitl": {
            "toc_status": toc_status,
            "layout_ok": layout_ok,
            "last_section_id": hitl.get("last_section_id"),
        },
        "phase": phase,
        "updated_at": (manifest or {}).get("updated_at") or (structure or {}).get("created_at"),
    }


def list_read_edition_sessions(*, corpus: Path | None = None) -> list[dict[str, Any]]:
    """Works that already have a Read Edition package on disk (in-progress or done).

    Uses catalog ``content_hash`` to locate ``package_dir`` — does not strip manuscripts.
    """
    from ..catalog import load_works

    root = corpus or corpus_root()
    works_path = root / "catalog" / "works.json"
    if not works_path.is_file():
        return []
    sessions: list[dict[str, Any]] = []
    for work in load_works(works_path):
        work_id = str(work.get("id") or "")
        content_hash = str(work.get("content_hash") or "")
        if not work_id or not content_hash:
            continue
        package_dir = package_root(work_id, content_hash, corpus=root)
        structure = load_structure(package_dir)
        manifest = load_manifest(package_dir)
        if structure is None and manifest is None:
            continue
        hitl = dict((structure or {}).get("hitl") or {})
        chapters = (manifest or {}).get("chapters") or []
        parsed = sum(1 for row in chapters if row.get("micro_status") == "complete")
        total = len(chapters) or len((structure or {}).get("sections") or [])
        sessions.append(
            {
                "work_id": work_id,
                "title": work.get("title"),
                "language": work.get("language"),
                "phase": _read_edition_phase(structure, manifest),
                "chapters_total": total,
                "chapters_parsed": parsed,
                "toc_status": (hitl.get("toc") or {}).get("status"),
                "layout_ok": bool(hitl.get("layout_ok")),
                "last_section_id": hitl.get("last_section_id"),
                "updated_at": (manifest or {}).get("updated_at") or (structure or {}).get("created_at"),
                "publishable": structure is not None and total > 0 and parsed == total,
                "macro_mode": (structure or {}).get("mode") or (manifest or {}).get("macro_mode"),
            }
        )
    sessions.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return sessions


def qa_read_edition_chapter(
    work_id: str,
    chapter_id: str,
    *,
    corpus: Path | None = None,
    use_llm: bool = True,
    model: str | None = None,
    min_overall: float = 7.0,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    package_dir, _meta, work = package_dir_for_work(work_id, corpus=root)
    chapter = load_chapter(package_dir, chapter_id)
    if not chapter.get("blocks"):
        raise ReadEditionError(f"{chapter_id} not parsed — run micro parse first")
    text, _, _ = resolve_stripped_source(work_id, corpus=root)
    structure = load_structure(package_dir)
    source_excerpt = chapter.get("reading_markdown") or ""
    if structure:
        section = next((s for s in structure.get("sections") or [] if s["section_id"] == chapter_id), None)
        if section:
            source_excerpt = section_source_slice(text, section)
    sub_edition = {
        "edition_format": "ref/1",
        "language": work.get("language") or "en",
        "blocks": chapter["blocks"],
        "reading_markdown": chapter.get("reading_markdown") or "",
        "content_kind": chapter.get("content_kind") or "prose",
        "source_family": (structure or {}).get("source_family") or "plain",
        "edition_hash": chapter.get("edition_hash") or "0" * 64,
    }
    qa = qa_read_edition(
        source_excerpt,
        sub_edition,
        language=str(work.get("language") or "en"),
        use_llm=use_llm,
        model=model,
        min_overall=min_overall,
    )
    qa["chapter_id"] = chapter_id
    save_qa_chapter(package_dir, chapter_id, qa)
    return qa


def qa_all_chapters(
    work_id: str,
    *,
    corpus: Path | None = None,
    use_llm: bool = True,
    chapter_ids: list[str] | None = None,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    result = build_read_edition_package(work_id, corpus=root)
    manifest = result["manifest"]
    ids = chapter_ids or [row["chapter_id"] for row in manifest.get("chapters") or []]
    reports: dict[str, Any] = {}
    passed = 0
    for ch_id in ids:
        qa = qa_read_edition_chapter(work_id, ch_id, corpus=root, use_llm=use_llm)
        reports[ch_id] = qa
        if qa.get("passed"):
            passed += 1
    return {
        "work_id": work_id,
        "chapters_qa": len(ids),
        "passed": passed,
        "reports": reports,
    }


def _chapter_label(section: dict[str, Any], used: dict[str, int]) -> str:
    raw_label = str(section.get("title") or section["section_id"]).strip()
    label = re.sub(r"[^A-Za-z0-9]", "", raw_label)[:16] or section["section_id"].replace("sec-", "")
    count = used.get(label, 0) + 1
    used[label] = count
    return label if count == 1 else f"{label[:12]}{count}"


def parsed_chapter_source(chapter: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Visible parsed text (matcher + Final Touch) plus the block graph."""
    blocks = list(chapter.get("blocks") or [])
    text = translation_source_from_blocks(blocks)
    if not text:
        text = str(chapter.get("reading_markdown") or "").strip()
    return text, blocks


def chapters_for_translation(
    work_id: str,
    *,
    corpus: Path | None = None,
    include_front_matter: bool = False,
    require_parsed: bool = False,
) -> list[dict[str, Any]]:
    """Chapter texts for translation.

    Prefer parsed ``reading_markdown`` / blocks (sidenotes hidden, genealogy
    split, wrap reflowed). Fall back to a Gutenberg slice by macro offsets
    when a chapter has not been micro-parsed yet.
    """
    root = corpus or corpus_root()
    try:
        package_dir, _meta, _work = package_dir_for_work(work_id, corpus=root)
    except ReadEditionStepError as exc:
        raise ReadEditionError(str(exc)) from exc
    structure = load_structure(package_dir)
    if not structure:
        raise ReadEditionError("Run macro step before translation sync")
    used: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    stripped_text: str | None = None
    for section in structure.get("sections") or []:
        if section.get("kind") == "front_matter" and not include_front_matter:
            continue
        chapter_label = _chapter_label(section, used)
        parsed: dict[str, Any] | None = None
        try:
            parsed = load_chapter(package_dir, section["section_id"])
        except (ReadEditionError, FileNotFoundError, OSError):
            parsed = None
        blocks: list[dict[str, Any]] = []
        source_kind = "raw_slice"
        if parsed:
            text, blocks = parsed_chapter_source(parsed)
            if text:
                source_kind = "parsed"
        if source_kind != "parsed":
            if require_parsed:
                raise ReadEditionError(
                    f"{section['section_id']} not parsed — run micro parse before translation sync"
                )
            if stripped_text is None:
                stripped_text, _, _ = resolve_stripped_source(work_id, corpus=root)
            text = trim_trailing_wrap_toc(section_source_slice(stripped_text, section))
            blocks = []
            source_kind = "raw_slice"
        out.append(
            {
                "chapter": chapter_label,
                "title": section.get("title"),
                "text": text,
                "words": _word_count(text),
                "ref_chapter_id": section["section_id"],
                "source_kind": source_kind,
                "blocks": blocks,
            }
        )
    return out
