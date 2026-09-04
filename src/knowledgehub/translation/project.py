from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..catalog import get_work, is_hub_translation, work_has_manuscript
from ..paths import corpus_root
from ..settings import MODES, resolve_models
from .paths import (
    annotations_file,
    glossary_file,
    project_file,
    segments_dir,
    style_brief_file,
    translation_catalog_id,
    translation_dir,
)
from .parts import SPLIT_VERSION
from .segment import sample_segment, split_chapters

SOURCE_LANGUAGES = frozenset({"en", "eng", "english"})
DEFAULT_GLOSSARY = {"terms": [], "entities": []}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def translation_project_ready(source_work_id: str) -> bool:
    if not project_file(source_work_id).is_file():
        return False
    seg_dir = segments_dir(source_work_id)
    if not seg_dir.is_dir():
        return False
    return any(
        path.name.endswith(".json") and "-sample" not in path.name for path in seg_dir.glob("ch*.json")
    )


def list_project_ids() -> list[str]:
    root = corpus_root() / "translations"
    if not root.is_dir():
        return []
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and translation_project_ready(path.name)
    )


def translation_offer(work: dict[str, Any], *, project_ids: set[str] | None = None) -> dict[str, Any]:
    wid = str(work.get("id") or "")
    ids = project_ids if project_ids is not None else set(list_project_ids())
    derived = str(work.get("derived_from") or "")
    if is_hub_translation(work):
        return {
            "can_translate": False,
            "translate_block": "hub_translation",
            "has_translation_project": bool(derived) and derived in ids,
            "translation_source_id": derived or None,
        }
    lang = str(work.get("language") or "en").strip().lower()
    if lang not in SOURCE_LANGUAGES:
        return {
            "can_translate": False,
            "translate_block": "not_english",
            "has_translation_project": wid in ids,
            "translation_source_id": wid if wid in ids else None,
        }
    if not work_has_manuscript(work):
        return {
            "can_translate": False,
            "translate_block": "no_raw",
            "has_translation_project": wid in ids,
            "translation_source_id": wid if wid in ids else None,
        }
    return {
        "can_translate": True,
        "translate_block": None,
        "has_translation_project": wid in ids,
        "translation_source_id": wid if wid in ids else None,
    }


def _require_translatable(work: dict[str, Any]) -> None:
    wid = str(work.get("id") or "")
    if is_hub_translation(work):
        raise ValueError(f"{wid} is already a Hub translation")
    lang = str(work.get("language") or "en").strip().lower()
    if lang not in SOURCE_LANGUAGES:
        raise ValueError(f"Only English sources can be translated (got {lang!r})")


def _style_brief(work: dict[str, Any], mode: str | None) -> str:
    title = str(work.get("title") or work.get("id") or "Untitled")
    author = str(work.get("author_id") or "").strip()
    year = work.get("year")
    source = ", ".join(part for part in (author, str(year) if year not in (None, "") else "") if part)
    mode_line = (
        f"- **Mode:** {mode} — locked at project start."
        if mode
        else "- **Mode:** locked when the curator picks tight / normal / loose."
    )
    return (
        f"# Style brief — {title}\n\n"
        + (f"- **Source:** {source}\n" if source else "")
        + "- **Voice:** stay close to the source register; do not modernize or flatten the argument.\n"
        + "- **Audience:** Vietnamese readers who may not know the original language.\n"
        + f"{mode_line}\n"
    )


def _manuscript_text(work: dict[str, Any], raw_path: Path) -> str:
    from ..edition.pipeline import build_edition

    raw = raw_path.read_text(encoding="utf-8")
    language = str(work.get("language") or "en")
    text, _report = build_edition(
        raw, language=language, work=work, use_llm=False, strip_only=True
    )
    return text if text.strip() else raw


def _chapters_for_init(work: dict[str, Any], raw_path: Path) -> tuple[list[dict[str, Any]], str]:
    """Chapter list for a new project. Never calls an LLM — draft/QA stay on the desk."""
    work_id = str(work.get("id") or "")
    try:
        from ..edition.read_edition import ReadEditionError, chapters_for_translation
        from ..edition.read_edition_steps import ReadEditionStepError

        rows = chapters_for_translation(work_id)
        if rows:
            return rows, "ref"
    except (ReadEditionError, ReadEditionStepError, FileNotFoundError, OSError, KeyError, ValueError):
        pass
    return split_chapters(_manuscript_text(work, raw_path)), "split"


def _write_sample(source_work_id: str, chapter: dict[str, str | int]) -> Path:
    ch = str(chapter["chapter"])
    sample_path = segments_dir(source_work_id) / f"ch{ch.lower()}-sample.json"
    sample_path.write_text(
        json.dumps(
            {
                "id": f"{source_work_id}--ch{ch.lower()}-sample",
                "chapter": ch,
                "words": chapter["words"],
                "source_text": chapter["text"],
                "drafts": {"tight": None, "normal": None, "loose": None},
                "final": None,
                "status": "pending",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return sample_path


def init_translation_project(
    source_work_id: str,
    *,
    target_language: str = "vi",
    translation_work_id: str | None = None,
    translation_mode: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    work = get_work(source_work_id)
    _require_translatable(work)
    if translation_mode is not None and translation_mode not in MODES:
        raise ValueError(f"Unknown mode {translation_mode!r}; expected one of {list(MODES)}")
    raw_rel = work.get("content_file")
    if not raw_rel:
        raise FileNotFoundError(f"{source_work_id} has no content_file")
    raw_path = corpus_root() / raw_rel
    if not raw_path.is_file():
        raise FileNotFoundError(
            f"Missing manuscript: {raw_path}\nRun: knowledgehub fetch-raw --work {source_work_id}"
        )

    root = translation_dir(source_work_id)
    ready = translation_project_ready(source_work_id)
    if ready and not overwrite:
        raise FileExistsError(
            f"Translation project exists: {root}\nUse --overwrite to recreate."
        )

    # Split before creating the dest dir so a failed/hung split cannot leave
    # an empty folder that 409s on retry while GET still 404s (no project.json).
    chapters, chapter_source = _chapters_for_init(work, raw_path)
    if not chapters:
        raise ValueError(f"{source_work_id} produced no chapters")

    root.mkdir(parents=True, exist_ok=True)
    seg_dir = segments_dir(source_work_id)
    seg_dir.mkdir(parents=True, exist_ok=True)
    if overwrite or not ready:
        for leftover in seg_dir.glob("*.json"):
            leftover.unlink()

    translation_work_id = translation_work_id or translation_catalog_id(
        source_work_id, target_language
    )
    locked = translation_mode in MODES
    project: dict[str, Any] = {
        "source_work_id": source_work_id,
        "translation_work_id": translation_work_id,
        "target_language": target_language,
        "translation_mode": translation_mode if locked else None,
        "translation_modes_available": list(MODES),
        "status": "mode_locked" if locked else "mode_pending",
        "created_at": _now(),
        "updated_at": _now(),
        "split_version": SPLIT_VERSION,
        "models": resolve_models(),
        "source": {
            "title": work.get("title"),
            "language": work.get("language"),
            "words": sum(int(c["words"]) for c in chapters),
            "chapters": len(chapters),
        },
        "segments_total": len(chapters),
        "chapter_source": chapter_source,
    }
    kinds = {str(row.get("source_kind") or "") for row in chapters if row.get("source_kind")}
    if kinds == {"parsed"}:
        project["source_text_kind"] = "parsed"
    elif kinds == {"raw_slice"}:
        project["source_text_kind"] = "raw_slice"
    elif len(kinds) > 1:
        project["source_text_kind"] = "mixed"

    sample_path: Path | None = None
    if not locked:
        first = sample_segment(chapters)
        sample_path = _write_sample(source_work_id, first)
        project["status"] = "sample_pending"
        project["sample_segment"] = {
            "chapter": first["chapter"],
            "words": first["words"],
            "file": f"segments/ch{str(first['chapter']).lower()}-sample.json",
        }

    from .titles import merge_segment_title_vi, translate_chapter_titles

    en_titles = [str(row.get("title") or row["chapter"]) for row in chapters]
    vi_titles = translate_chapter_titles(en_titles, use_llm=False)

    for index, row in enumerate(chapters):
        seg_id = f"ch{str(row['chapter']).lower()}"
        seg_path = segments_dir(source_work_id) / f"{seg_id}.json"
        payload = {
            "id": f"{source_work_id}--{seg_id}",
            "chapter": row["chapter"],
            "source_order": index,
            "words": row["words"],
            "source_text": row["text"],
            "drafts": {"tight": None, "normal": None, "loose": None},
            "final": None,
            "status": "pending",
            "title_vi": vi_titles[index],
        }
        if row.get("source_kind"):
            payload["source_text_kind"] = row["source_kind"]
        if row.get("ref_chapter_id"):
            payload["ref_chapter_id"] = row["ref_chapter_id"]
        if row.get("title"):
            payload["ref_title"] = row["title"]
        if row.get("blocks"):
            from .ref_chapters import ref_blocks_for_translation

            payload["ref_blocks"] = ref_blocks_for_translation(list(row.get("blocks") or []))
        seg_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    glossary_file(source_work_id).write_text(
        json.dumps(DEFAULT_GLOSSARY, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    annotations_file(source_work_id).write_text(
        json.dumps({"annotations": []}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    style_brief_file(source_work_id).write_text(_style_brief(work, translation_mode if locked else None), encoding="utf-8")
    project_file(source_work_id).write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    llm_titles = translate_chapter_titles(en_titles)
    for index, title_vi in enumerate(llm_titles):
        if title_vi == vi_titles[index]:
            continue
        seg_id = f"ch{str(chapters[index]['chapter']).lower()}"
        merge_segment_title_vi(segments_dir(source_work_id) / f"{seg_id}.json", title_vi)

    paths = {"root": str(root.relative_to(corpus_root()))}
    if sample_path is not None:
        paths["sample"] = str(sample_path.relative_to(corpus_root()))
    return {"project": project, "paths": paths}


def load_project(source_work_id: str) -> dict[str, Any]:
    path = project_file(source_work_id)
    if not path.is_file():
        raise FileNotFoundError(f"No translation project: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def select_translation_mode(source_work_id: str, mode: str) -> dict[str, Any]:
    project = load_project(source_work_id)
    available = project.get("translation_modes_available") or list(MODES)
    if mode not in available:
        raise ValueError(f"Unknown mode {mode!r}; expected one of {available}")

    sample_path: Path | None = None
    chapter_path: Path | None = None
    sample_rel = (project.get("sample_segment") or {}).get("file")
    if sample_rel:
        sample_path = segments_dir(source_work_id) / Path(sample_rel).name
        if sample_path.is_file():
            segment = json.loads(sample_path.read_text(encoding="utf-8"))
            chosen = (segment.get("drafts") or {}).get(mode)
            if chosen:
                segment["final"] = chosen
                segment["status"] = "approved"
                sample_path.write_text(
                    json.dumps(segment, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                chapter = str(segment.get("chapter") or "").lower()
                chapter_path = segments_dir(source_work_id) / f"ch{chapter}.json"
                if chapter_path.is_file():
                    chapter_seg = json.loads(chapter_path.read_text(encoding="utf-8"))
                    chapter_seg["final"] = chosen
                    chapter_seg.setdefault("drafts", {})[mode] = chosen
                    if segment.get("draft_raw", {}).get(mode):
                        chapter_seg.setdefault("draft_raw", {})[mode] = segment["draft_raw"][mode]
                    chapter_seg["status"] = "draft_ready"
                    chapter_path.write_text(
                        json.dumps(chapter_seg, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )

    project["translation_mode"] = mode
    project["status"] = "mode_locked"
    project["updated_at"] = _now()
    project_file(source_work_id).write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "work_id": source_work_id,
        "translation_mode": mode,
        "status": project["status"],
        "sample": str(sample_path.relative_to(corpus_root())) if sample_path and sample_path.is_file() else None,
        "chapter_segment": str(chapter_path.relative_to(corpus_root())) if chapter_path and chapter_path.is_file() else None,
    }
