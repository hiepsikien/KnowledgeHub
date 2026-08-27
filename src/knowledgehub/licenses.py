from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import licenses_path

_ARCHIVE_YEAR = re.compile(r"^public_domain_usa_archive_\d{4}$")
_USA_YEAR = re.compile(r"^public_domain_usa_\d{4}$")


def load_license_catalog(path: Path | None = None) -> dict:
    data = json.loads((path or licenses_path()).read_text(encoding="utf-8"))
    data.setdefault("licenses", [])
    data.setdefault("aliases", {})
    return data


def known_ids(catalog: dict | None = None) -> set[str]:
    cat = catalog or load_license_catalog()
    ids = {str(row["id"]) for row in cat.get("licenses") or [] if row.get("id")}
    ids.update(str(k) for k in (cat.get("aliases") or {}))
    return ids


def canonical_license(license_id: str, catalog: dict | None = None) -> str:
    raw = (license_id or "").strip()
    cat = catalog or load_license_catalog()
    aliases = {str(k): str(v) for k, v in (cat.get("aliases") or {}).items()}
    if raw in aliases:
        return aliases[raw]
    ids = {str(row["id"]) for row in cat.get("licenses") or [] if row.get("id")}
    if raw in ids:
        return raw
    if _ARCHIVE_YEAR.match(raw):
        return "public_domain_usa_archive"
    if _USA_YEAR.match(raw):
        return "public_domain_usa_gutenberg"
    if raw in {"public_domain_usa", "public_domain_original", "public_domain_primary_excerpt"}:
        return "public_domain_usa_gutenberg"
    if raw in {"public_domain_usa_journal", "public_domain_usa_wikisource", "public_domain_usa_wikisource_legge"}:
        return "public_domain_usa_gutenberg"
    if raw.startswith("public_domain_vn"):
        return "public_domain_vn_wikisource"
    return raw


def license_allowed(license_id: str, catalog: dict | None = None) -> bool:
    raw = (license_id or "").strip()
    if not raw:
        return False
    cat = catalog or load_license_catalog()
    canon = canonical_license(raw, cat)
    ids = {str(row["id"]) for row in cat.get("licenses") or [] if row.get("id")}
    return canon in ids
