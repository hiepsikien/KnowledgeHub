from __future__ import annotations

import json
from pathlib import Path

from .catalog import content_sha256, is_hub_translation, load_works, resolve_content_path
from .paths import corpus_root


def refresh_hashes(*, corpus: Path | None = None) -> dict[str, int]:
    from .translation.assemble import assemble_finals

    root = corpus or corpus_root()
    path = root / "catalog" / "works.json"
    works = load_works(path)
    hashed = missing = unchanged = 0
    for work in works:
        if is_hub_translation(work):
            source_id = str(work.get("derived_from") or "")
            try:
                _, meta = assemble_finals(source_id, require_complete=True)
            except (FileNotFoundError, ValueError):
                missing += 1
                continue
            digest = meta["content_hash"]
        else:
            try:
                file_path = resolve_content_path(work, root=root)
            except ValueError:
                missing += 1
                continue
            if not file_path.is_file():
                missing += 1
                continue
            digest = content_sha256(file_path)
        if work.get("content_hash") == digest:
            unchanged += 1
            continue
        work["content_hash"] = digest
        hashed += 1
    path.write_text(json.dumps(works, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"updated": hashed, "unchanged": unchanged, "missing_raw": missing}
