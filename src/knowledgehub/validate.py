from __future__ import annotations

from pathlib import Path

from .catalog import WORK_ID, load_authors, load_works, resolve_content_path
from .licenses import license_allowed
from .paths import corpus_root


def validate_catalog(*, corpus: Path | None = None) -> list[str]:
    root = corpus or corpus_root()
    errors: list[str] = []
    authors = {a["id"]: a for a in load_authors(root / "catalog" / "authors.json")}
    works = load_works(root / "catalog" / "works.json")
    seen: set[str] = set()
    for work in works:
        wid = str(work.get("id") or "")
        if not WORK_ID.match(wid):
            errors.append(f"bad id: {wid!r}")
        if wid in seen:
            errors.append(f"duplicate id: {wid}")
        seen.add(wid)
        author_id = str(work.get("author_id") or "")
        if author_id not in authors:
            errors.append(f"{wid}: unknown author_id {author_id}")
        if not work.get("title"):
            errors.append(f"{wid}: missing title")
        if not license_allowed(str(work.get("license") or "")):
            errors.append(f"{wid}: license not in catalog: {work.get('license')}")
        path = resolve_content_path(work, root=root)
        if work.get("content_hash") and not path.is_file():
            errors.append(f"{wid}: hashed but missing file {path}")
    return errors
