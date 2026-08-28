from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .licenses import canonical_license, load_license_catalog
from .paths import (
    catalog_authors_path,
    catalog_dir,
    catalog_works_path,
    corpus_root,
    sources_root,
)

WORK_ID = re.compile(r"^[a-z][a-z0-9_]{0,40}--[a-z0-9_]{1,80}$")


def work_id(brain: str, filename: str) -> str:
    stem = Path(filename).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "work"
    return f"{brain}--{stem[:80]}"


def content_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _guess_lang(row: dict[str, Any]) -> str:
    lang = str(row.get("lang") or "").lower().strip()
    if lang in {"en", "vi", "fr", "ja"}:
        return lang
    return "en"


def _guess_read_category(brain: str, row: dict[str, Any]) -> str:
    chunking = str(row.get("chunking") or "")
    if chunking == "verse":
        return "poetry"
    concepts = " ".join(row.get("concepts") or []).lower()
    if any(k in concepts for k in ("memoir", "autobiograph", "life")):
        return "memoir-biography"
    if brain in {"nam_cao", "nguyen_du", "shakespeare", "austen", "dickens"}:
        return "literary-fiction"
    return "essays"


def is_hub_translation(work: dict[str, Any]) -> bool:
    return work.get("origin") == "hub_translation"


def _preserved_translations(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        rows = load_works(path)
    except ValueError:
        return []
    return [row for row in rows if is_hub_translation(row) and row.get("id")]


def load_think_sources(src: Path | None = None) -> list[tuple[str, dict[str, Any]]]:
    root = src or sources_root()
    out: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(root.glob("*/works.json")):
        brain = path.parent.name
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        for row in data:
            if isinstance(row, dict) and row.get("file"):
                out.append((brain, row))
    return out


def build_catalog(*, src: Path | None = None, dest: Path | None = None) -> dict[str, Any]:
    license_cat = load_license_catalog()
    sources = src or sources_root()
    rows = load_think_sources(sources)
    authors: dict[str, dict[str, Any]] = {}
    works: list[dict[str, Any]] = []
    seen: set[str] = set()

    for brain, row in rows:
        authors.setdefault(
            brain,
            {
                "id": brain,
                "name": brain.replace("_", " ").title(),
                "think_brain": brain,
            },
        )
        filename = str(row["file"])
        wid = work_id(brain, filename)
        if wid in seen:
            raise ValueError(f"duplicate work id: {wid}")
        seen.add(wid)
        rel = f"sources/{brain}/raw/{filename}"
        raw_path = sources / brain / "raw" / filename
        digest = content_sha256(raw_path) if raw_path.is_file() else None
        works.append(
            {
                "id": wid,
                "title": str(row.get("work") or Path(filename).stem),
                "author_id": brain,
                "language": _guess_lang(row),
                "year": row.get("year"),
                "description": "",
                "license": canonical_license(str(row.get("license") or ""), license_cat),
                "license_source": str(row.get("license") or ""),
                "source_url": str(row.get("source_url") or ""),
                "gutenberg_id": row.get("gutenberg_id"),
                "translator": row.get("translator"),
                "concepts": list(row.get("concepts") or []),
                "content_file": rel,
                "think_brain": brain,
                "think_file": filename,
                "content_hash": digest,
                "version": 1,
                "status": "draft",
                "rights": {
                    "basis": "public_domain",
                    "consumers": {"think": "allowed", "read": "blocked"},
                },
                "read": {
                    "category_slug": _guess_read_category(brain, row),
                    "price_cents": 0,
                    "split_length": "standard",
                },
            }
        )

    out_dir = dest or catalog_dir()
    dest_works = out_dir / "works.json"
    for row in _preserved_translations(dest_works):
        wid = str(row["id"])
        if wid in seen:
            continue
        seen.add(wid)
        works.append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    authors_list = sorted(authors.values(), key=lambda a: a["id"])
    (out_dir / "authors.json").write_text(
        json.dumps(authors_list, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "works.json").write_text(
        json.dumps(works, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"authors": len(authors_list), "works": len(works)}


def load_works(path: Path | None = None) -> list[dict[str, Any]]:
    data = json.loads((path or catalog_works_path()).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("catalog/works.json must be a list")
    return data


def load_authors(path: Path | None = None) -> list[dict[str, Any]]:
    data = json.loads((path or catalog_authors_path()).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("catalog/authors.json must be a list")
    return data


def get_work(work_id_value: str, *, corpus: Path | None = None) -> dict[str, Any]:
    path = (corpus / "catalog" / "works.json") if corpus else catalog_works_path()
    for row in load_works(path):
        if row.get("id") == work_id_value:
            return row
    raise KeyError(work_id_value)


def resolve_content_path(work: dict[str, Any], *, root: Path | None = None) -> Path:
    base = root or corpus_root()
    rel = work.get("content_file")
    if not rel:
        raise ValueError(f"{work.get('id')}: no content_file")
    return (base / str(rel)).resolve()


def work_has_manuscript(work: dict[str, Any], *, root: Path | None = None) -> bool:
    if is_hub_translation(work):
        from .translation.assemble import translation_status

        source_id = str(work.get("derived_from") or "")
        return bool(source_id) and translation_status(source_id)["complete"]
    try:
        return resolve_content_path(work, root=root).is_file()
    except ValueError:
        return False


def upsert_work(work: dict[str, Any], *, corpus: Path | None = None) -> dict[str, Any]:
    root = corpus or corpus_root()
    path = root / "catalog" / "works.json"
    works = load_works(path)
    wid = str(work["id"])
    replaced = False
    for index, row in enumerate(works):
        if row.get("id") == wid:
            works[index] = work
            replaced = True
            break
    if not replaced:
        works.append(work)
    path.write_text(json.dumps(works, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return work


def read_allowed(work: dict[str, Any]) -> bool:
    return ((work.get("rights") or {}).get("consumers") or {}).get("read") == "allowed"


def work_summary(work: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    digest = work.get("content_hash")
    return {
        "id": work.get("id"),
        "title": work.get("title"),
        "author_id": work.get("author_id"),
        "language": work.get("language") or "en",
        "year": work.get("year"),
        "license": work.get("license"),
        "status": work.get("status") or "draft",
        "version": work.get("version") or 1,
        "read_allowed": read_allowed(work),
        "has_raw": work_has_manuscript(work, root=root),
        "has_hash": bool(digest),
        "content_hash": digest,
        "origin": work.get("origin"),
        "derived_from": work.get("derived_from"),
        "category_slug": (work.get("read") or {}).get("category_slug") or "essays",
        "price_cents": int((work.get("read") or {}).get("price_cents") or 0),
        "split_length": (work.get("read") or {}).get("split_length") or "standard",
        "description": work.get("description") or "",
        "source_url": work.get("source_url") or "",
    }


def catalog_stats(*, corpus: Path | None = None) -> dict[str, Any]:
    root = corpus or corpus_root()
    works = load_works(root / "catalog" / "works.json")
    authors = load_authors(root / "catalog" / "authors.json")
    summaries = [work_summary(w, root=root) for w in works]
    return {
        "works": len(summaries),
        "authors": len(authors),
        "read_allowed": sum(1 for s in summaries if s["read_allowed"]),
        "has_raw": sum(1 for s in summaries if s["has_raw"]),
        "missing_raw": sum(1 for s in summaries if not s["has_raw"]),
        "hashed": sum(1 for s in summaries if s["has_hash"]),
        "languages": sorted({s["language"] for s in summaries}),
    }


def set_read_consumer(work_id_value: str, allowed: bool, *, corpus: Path | None = None) -> dict[str, Any]:
    root = corpus or corpus_root()
    path = root / "catalog" / "works.json"
    works = load_works(path)
    found = None
    for row in works:
        if row.get("id") == work_id_value:
            rights = row.setdefault("rights", {})
            consumers = rights.setdefault("consumers", {})
            consumers["read"] = "allowed" if allowed else "blocked"
            found = row
            break
    if found is None:
        raise KeyError(work_id_value)
    path.write_text(json.dumps(works, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return found


def update_read_publication(
    work_id_value: str,
    *,
    title: str | None = None,
    description: str | None = None,
    category_slug: str | None = None,
    price_cents: int | None = None,
    split_length: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    from .read_options import validate_category_slug, validate_split_length

    root = corpus or corpus_root()
    path = root / "catalog" / "works.json"
    works = load_works(path)
    found = None
    for row in works:
        if row.get("id") == work_id_value:
            if title is not None:
                cleaned = title.strip()
                if cleaned:
                    row["title"] = cleaned
            if description is not None:
                row["description"] = description.strip()
            read = row.setdefault("read", {})
            if category_slug is not None:
                read["category_slug"] = validate_category_slug(category_slug)
            if price_cents is not None:
                read["price_cents"] = max(0, int(price_cents))
            if split_length is not None:
                read["split_length"] = validate_split_length(split_length)
            found = row
            break
    if found is None:
        raise KeyError(work_id_value)
    path.write_text(json.dumps(works, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return found
