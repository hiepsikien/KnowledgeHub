"""Build, load, and QA per-chapter Read Edition (REF/1) packages on disk."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..catalog import get_work, is_hub_translation, resolve_content_path
from ..paths import corpus_root
from .cache import load_cached_edition, save_cached_edition
from .overrides import apply_chapter_overrides, overrides_digest
from .ref import build_read_edition
from .ref_schema import validate_edition
from .serialize import blocks_to_markdown
from .ref_qa import qa_read_edition

READ_EDITION_PACKAGE_VERSION = "1"
REF_PARSER_VERSION = "1.7"


class ReadEditionError(RuntimeError):
    pass


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
    use_llm: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Build or load REF/1 edition for a catalog work. Returns (edition, report, stripped_source)."""
    from ..normalize import normalize_manuscript
    from ..translation.assemble import assemble_finals

    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)

    if is_hub_translation(work):
        source_id = str(work.get("derived_from") or "")
        text, meta = assemble_finals(source_id, require_complete=True)
        content_hash = str(meta["content_hash"])
        cached = load_cached_edition(work_id, content_hash, corpus=root)
        if cached:
            edition = cached
            report = {"ref_mode": "cache", "origin": "hub_translation", "chapters": meta["chapters"]}
        else:
            edition, ref_report = build_read_edition(
                text,
                family="plain",
                language=str(work.get("language") or "vi"),
                work_id=work_id,
            )
            save_cached_edition(work_id, content_hash, edition, corpus=root, report=ref_report)
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
            use_llm=use_llm,
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
    (qa_dir / "overrides.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_path = package_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["overrides_hash"] = overrides_digest(chapters)
        manifest["updated_at"] = payload["updated_at"]
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    report = load_qa_report(package_dir)
    chapters = dict(report.get("chapters") or {})
    chapters[chapter_id] = qa
    report["chapters"] = chapters
    report["updated_at"] = _now()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    use_llm: bool = False,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)
    edition, report, _source = resolve_edition(work_id, corpus=root, use_llm=use_llm)
    errors = validate_edition(edition)
    if errors:
        raise ReadEditionError(f"REF validation failed: {'; '.join(errors[:5])}")

    edition_hash = str(edition["edition_hash"])
    package_dir = read_edition_dir(work_id, edition_hash, corpus=root)
    if package_dir.is_dir() and not force:
        manifest = load_manifest(package_dir)
        if manifest:
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


def package_status(work_id: str, *, corpus: Path | None = None) -> dict[str, Any]:
    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)
    try:
        edition, report, _ = resolve_edition(work_id, corpus=root)
    except ReadEditionError as exc:
        return {"work_id": work_id, "ready": False, "error": str(exc)}
    edition_hash = edition.get("edition_hash")
    package_dir = read_edition_dir(work_id, str(edition_hash), corpus=root)
    manifest = load_manifest(package_dir) if package_dir.is_dir() else None
    qa = load_qa_report(package_dir) if package_dir.is_dir() else {"chapters": {}}
    overrides = load_overrides(package_dir) if package_dir.is_dir() else {}
    return {
        "work_id": work_id,
        "title": work.get("title"),
        "language": edition.get("language") or work.get("language"),
        "ready": True,
        "edition_hash": edition_hash,
        "content_hash": report.get("content_hash") or work.get("content_hash"),
        "content_kind": edition.get("content_kind"),
        "block_count": len(edition.get("blocks") or []),
        "package_built": manifest is not None,
        "package_dir": str(package_dir.relative_to(root)) if package_dir.is_dir() else None,
        "manifest": manifest,
        "qa_chapters": len(qa.get("chapters") or {}),
        "override_chapters": len(overrides),
    }


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
    edition, _report, source = resolve_edition(work_id, corpus=root)
    build_read_edition_package(work_id, corpus=root)
    package_dir = read_edition_dir(work_id, str(edition["edition_hash"]), corpus=root)
    chapter = load_chapter(package_dir, chapter_id)
    sub_edition = {
        **edition,
        "blocks": chapter["blocks"],
        "reading_markdown": chapter["reading_markdown"],
    }
    source_excerpt = chapter["reading_markdown"]
    if source and chapter.get("block_start") is not None:
        source_excerpt = source[:8000]
    qa = qa_read_edition(
        source_excerpt,
        sub_edition,
        language=str(edition.get("language") or "en"),
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


def chapters_for_translation(work_id: str, *, corpus: Path | None = None) -> list[dict[str, str | int]]:
    """Chapter texts aligned to REF split_hints — for translation segmentation."""
    root = corpus or corpus_root()
    edition, _, _ = resolve_edition(work_id, corpus=root)
    specs = split_edition_chapters(edition)
    used: dict[str, int] = {}
    out: list[dict[str, str | int]] = []
    for spec in specs:
        ch = chapter_document(edition, spec)
        hint = spec.get("split_hint") or {}
        raw_label = str(hint.get("text") or spec["chapter_id"]).strip()
        label = re.sub(r"[^A-Za-z0-9]", "", raw_label)[:16] or spec["chapter_id"].replace("ch-", "")
        count = used.get(label, 0) + 1
        used[label] = count
        chapter_label = label if count == 1 else f"{label[:12]}{count}"
        out.append(
            {
                "chapter": chapter_label,
                "title": spec["title"],
                "text": ch["reading_markdown"],
                "words": ch["word_count"],
                "ref_chapter_id": spec["chapter_id"],
            }
        )
    return out
