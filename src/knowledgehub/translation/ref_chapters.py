"""Align translation chapter segments with REF split_hints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..edition.read_edition import ReadEditionError, chapters_for_translation
from ..paths import corpus_root
from .paths import project_file, segments_dir
from .project import load_project


def sync_translation_chapters_from_ref(
    source_work_id: str,
    *,
    overwrite: bool = False,
    include_front_matter: bool = False,
    corpus: Path | None = None,
) -> dict[str, Any]:
    """Rewrite segment source_text from REF chapter boundaries (opt-in)."""
    root = corpus or corpus_root()
    proj_path = project_file(source_work_id)
    if not proj_path.is_file():
        raise FileNotFoundError(f"No translation project for {source_work_id}")

    try:
        ref_chapters = chapters_for_translation(source_work_id, corpus=root)
    except ReadEditionError as exc:
        raise ValueError(str(exc)) from exc

    if not include_front_matter:
        ref_chapters = [c for c in ref_chapters if c.get("ref_chapter_id") != "ch-000-front"]

    seg_dir = segments_dir(source_work_id)
    existing = sorted(seg_dir.glob("ch*.json"))
    non_sample = [p for p in existing if "-sample" not in p.name]
    if non_sample and not overwrite:
        raise FileExistsError(
            f"{len(non_sample)} segment files exist — pass overwrite=True to replace from REF chapters"
        )

    for leftover in seg_dir.glob("ch*.json"):
        if "-sample" not in leftover.name:
            leftover.unlink()

    written: list[str] = []
    for row in ref_chapters:
        ch = str(row["chapter"])
        seg_id = f"ch{ch.lower()}"
        seg_path = seg_dir / f"{seg_id}.json"
        payload = {
            "id": f"{source_work_id}--{seg_id}",
            "chapter": ch,
            "words": row["words"],
            "source_text": row["text"],
            "drafts": {"tight": None, "normal": None, "loose": None},
            "final": None,
            "status": "pending",
            "ref_chapter_id": row.get("ref_chapter_id"),
            "ref_title": row.get("title"),
        }
        seg_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(seg_id)

    project = load_project(source_work_id)
    project["chapter_source"] = "ref"
    project["segments_total"] = len(written)
    project["source"]["chapters"] = len(written)
    project["source"]["words"] = sum(int(c["words"]) for c in ref_chapters)
    project_file(source_work_id).write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "source_work_id": source_work_id,
        "segments_written": len(written),
        "segment_ids": written,
        "chapter_source": "ref",
    }
