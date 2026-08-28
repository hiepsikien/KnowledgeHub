"""Promote a complete translation into a catalog Work (not into sources/raw)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..catalog import get_work, is_hub_translation, upsert_work
from ..paths import corpus_root
from .assemble import assemble_finals
from .paths import project_file, translation_catalog_id
from .project import load_project


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def promote_translation(
    source_work_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    corpus=None,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    source = get_work(source_work_id, corpus=root)
    project = load_project(source_work_id)
    lang = str(project.get("target_language") or "vi")
    text, meta = assemble_finals(source_work_id, require_complete=True)
    catalog_id = translation_catalog_id(source_work_id, lang)
    source_title = str(source.get("title") or source_work_id)
    default_title = f"{source_title} (Tiếng Việt)" if lang == "vi" else f"{source_title} ({lang})"
    try:
        found = get_work(catalog_id, corpus=root)
    except KeyError:
        existing = None
    else:
        if not is_hub_translation(found):
            raise ValueError(f"{catalog_id} already exists in the catalog")
        existing = found
    rights = (existing or {}).get("rights") or {
        "basis": "editorial_derivative",
        "consumers": {"think": "blocked", "read": "blocked"},
    }
    rights["basis"] = "editorial_derivative"
    rights.setdefault("consumers", {})
    rights["consumers"].setdefault("think", "blocked")
    rights["consumers"].setdefault("read", "blocked")
    read = dict((existing or {}).get("read") or source.get("read") or {})
    read.setdefault("category_slug", (source.get("read") or {}).get("category_slug") or "essays")
    read.setdefault("price_cents", 0)
    read.setdefault("split_length", (source.get("read") or {}).get("split_length") or "standard")
    prev_hash = (existing or {}).get("content_hash")
    version = int((existing or {}).get("version") or 1)
    if prev_hash and prev_hash != meta["content_hash"]:
        version += 1
    work = {
        "id": catalog_id,
        "title": (title.strip() if title and title.strip() else None)
        or (existing or {}).get("title")
        or default_title,
        "author_id": source.get("author_id"),
        "language": lang,
        "year": source.get("year"),
        "description": description if description is not None else (existing or {}).get("description") or "",
        "license": "hub_editorial_vi",
        "license_source": source.get("license"),
        "source_url": source.get("source_url") or "",
        "translator": "Knowledge Hub",
        "derived_from": source_work_id,
        "origin": "hub_translation",
        "content_file": None,
        "think_brain": source.get("think_brain") or source.get("author_id"),
        "content_hash": meta["content_hash"],
        "version": version,
        "status": (existing or {}).get("status") or "draft",
        "rights": rights,
        "read": read,
    }
    upsert_work(work, corpus=root)
    project["translation_work_id"] = catalog_id
    project["updated_at"] = _now()
    project_file(source_work_id).write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "work": work,
        "assembled_chars": meta["chars"],
        "chapters": meta["chapters"],
        "created": existing is None,
    }
