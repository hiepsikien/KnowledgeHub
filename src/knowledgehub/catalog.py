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
    return (base / str(work["content_file"])).resolve()


def read_allowed(work: dict[str, Any]) -> bool:
    return ((work.get("rights") or {}).get("consumers") or {}).get("read") == "allowed"


def work_summary(work: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    path = resolve_content_path(work, root=root)
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
        "has_raw": path.is_file(),
        "has_hash": bool(digest),
        "content_hash": digest,
        "category_slug": (work.get("read") or {}).get("category_slug") or "essays",
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
