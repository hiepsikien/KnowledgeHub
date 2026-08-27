from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def corpus_root() -> Path:
    override = (os.environ.get("KNOWLEDGEHUB_CORPUS") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return repo_root() / "corpus"


def licenses_path() -> Path:
    return corpus_root() / "licenses.json"


def sources_root() -> Path:
    return corpus_root() / "sources"


def catalog_dir() -> Path:
    return corpus_root() / "catalog"


def catalog_works_path() -> Path:
    return catalog_dir() / "works.json"


def catalog_authors_path() -> Path:
    return catalog_dir() / "authors.json"
