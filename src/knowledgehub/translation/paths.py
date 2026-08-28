from __future__ import annotations

import re
from pathlib import Path

from ..paths import corpus_root

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
_SAFE_CHAPTER = re.compile(r"^[A-Za-z0-9]{1,16}$")
_LANG = re.compile(r"^[a-z]{2}$")


def safe_work_id(source_work_id: str) -> str:
    text = (source_work_id or "").strip()
    if not _SAFE_NAME.fullmatch(text) or ".." in text:
        raise ValueError(f"Invalid work id: {source_work_id!r}")
    return text


def safe_chapter(chapter: str) -> str:
    text = str(chapter or "").strip()
    if not _SAFE_CHAPTER.fullmatch(text):
        raise ValueError(f"Invalid chapter: {chapter!r}")
    return text


def translation_catalog_id(source_work_id: str, target_language: str = "vi") -> str:
    """Catalog id with one `--` so it matches WORK_ID: `{source}_{lang}`."""
    lang = (target_language or "vi").strip().lower()
    if not _LANG.fullmatch(lang):
        raise ValueError(f"Unsupported target language: {target_language!r}")
    return f"{safe_work_id(source_work_id)}_{lang}"


def translation_dir(source_work_id: str) -> Path:
    return corpus_root() / "translations" / safe_work_id(source_work_id)


def project_file(source_work_id: str) -> Path:
    return translation_dir(source_work_id) / "project.json"


def glossary_file(source_work_id: str) -> Path:
    return translation_dir(source_work_id) / "glossary.json"


def segments_dir(source_work_id: str) -> Path:
    return translation_dir(source_work_id) / "segments"


def annotations_file(source_work_id: str) -> Path:
    return translation_dir(source_work_id) / "annotations.json"


def style_brief_file(source_work_id: str) -> Path:
    return translation_dir(source_work_id) / "style_brief.md"
