from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..catalog import get_work
from ..paths import corpus_root
from .paths import (
    annotations_file,
    glossary_file,
    project_file,
    segments_dir,
    style_brief_file,
    translation_dir,
)
from .providers import DEFAULT_GEMINI_MODEL
from .segment import sample_segment, split_chapters

DEFAULT_STYLE_BRIEF = """# Style brief — Grotius, *The Freedom of the Seas*

- **Genre:** legal-political treatise (1609), arguing natural law and freedom of navigation.
- **Voice:** formal, argumentative, citations from Roman law/classical authors.
- **Audience:** Vietnamese readers without legal training — clarity without flattening the argument.
- **Terms:** lock Latin legal terms on first use; prefer consistency (*Law of Nations* → *luật các dân tộc* / *luật quốc tế* — pick one in glossary).
- **Mode (pilot):** Normal — balanced fidelity and readability.
"""

DEFAULT_GLOSSARY = {
    "terms": [
        {
            "id": "term-law-of-nations",
            "source": "Law of Nations",
            "target": None,
            "locked": False,
            "notes": "Primary term — decide in review",
        },
        {
            "id": "term-mare-liberum",
            "source": "freedom of the seas",
            "target": None,
            "locked": False,
            "notes": "Latin title Mare Liberum; may keep as proper phrase",
        },
        {
            "id": "term-voc",
            "source": "Dutch East India Company",
            "target": "VOC",
            "locked": True,
            "notes": "Use VOC with expand-on-first-mention annotation",
        },
    ],
    "entities": [],
}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def init_translation_project(
    source_work_id: str,
    *,
    target_language: str = "vi",
    translation_work_id: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    work = get_work(source_work_id)
    raw_rel = work.get("content_file")
    if not raw_rel:
        raise FileNotFoundError(f"{source_work_id} has no content_file")
    raw_path = corpus_root() / raw_rel
    if not raw_path.is_file():
        raise FileNotFoundError(
            f"Missing manuscript: {raw_path}\nRun: knowledgehub fetch-raw --work {source_work_id}"
        )

    root = translation_dir(source_work_id)
    if root.exists() and not overwrite:
        raise FileExistsError(
            f"Translation project exists: {root}\nUse --overwrite to recreate."
        )
    root.mkdir(parents=True, exist_ok=True)
    segments_dir(source_work_id).mkdir(parents=True, exist_ok=True)

    text = raw_path.read_text(encoding="utf-8")
    chapters = split_chapters(text)
    ch1 = sample_segment(chapters, chapter="I")

    translation_work_id = translation_work_id or f"{source_work_id}--{target_language}"
    project: dict[str, Any] = {
        "source_work_id": source_work_id,
        "translation_work_id": translation_work_id,
        "target_language": target_language,
        "translation_mode": None,
        "translation_modes_available": ["tight", "normal", "loose"],
        "status": "sample_pending",
        "created_at": _now(),
        "updated_at": _now(),
        "models": {
            "draft": "deepseek-chat",
            "polish": DEFAULT_GEMINI_MODEL,
            "qa": "deepseek-reasoner",
            "annotations": DEFAULT_GEMINI_MODEL,
        },
        "source": {
            "title": work.get("title"),
            "language": work.get("language"),
            "words": sum(int(c["words"]) for c in chapters),
            "chapters": len(chapters),
        },
        "sample_segment": {
            "chapter": ch1["chapter"],
            "words": ch1["words"],
            "file": f"segments/ch{ch1['chapter'].lower()}-sample.json",
        },
        "segments_total": len(chapters),
    }

    sample_payload = {
        "id": f"{source_work_id}--ch{ch1['chapter']}-sample",
        "chapter": ch1["chapter"],
        "words": ch1["words"],
        "source_text": ch1["text"],
        "drafts": {"tight": None, "normal": None, "loose": None},
        "final": None,
        "status": "pending",
    }

    project_file(source_work_id).write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sample_path = segments_dir(source_work_id) / f"ch{str(ch1['chapter']).lower()}-sample.json"
    sample_path.write_text(
        json.dumps(sample_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    glossary_file(source_work_id).write_text(
        json.dumps(DEFAULT_GLOSSARY, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    annotations_file(source_work_id).write_text(
        json.dumps({"annotations": []}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    style_brief_file(source_work_id).write_text(DEFAULT_STYLE_BRIEF, encoding="utf-8")

    for row in chapters:
        seg_id = f"ch{row['chapter'].lower()}"
        seg_path = segments_dir(source_work_id) / f"{seg_id}.json"
        if seg_path.exists():
            continue
        payload = {
            "id": f"{source_work_id}--{seg_id}",
            "chapter": row["chapter"],
            "words": row["words"],
            "source_text": row["text"],
            "drafts": {"tight": None, "normal": None, "loose": None},
            "final": None,
            "status": "pending",
        }
        seg_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "project": project,
        "paths": {
            "root": str(root.relative_to(corpus_root())),
            "sample": str(sample_path.relative_to(corpus_root())),
        },
    }


def load_project(source_work_id: str) -> dict[str, Any]:
    path = project_file(source_work_id)
    if not path.is_file():
        raise FileNotFoundError(f"No translation project: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
