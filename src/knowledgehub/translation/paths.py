from __future__ import annotations

from pathlib import Path

from ..paths import corpus_root


def translation_dir(source_work_id: str) -> Path:
    return corpus_root() / "translations" / source_work_id


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
