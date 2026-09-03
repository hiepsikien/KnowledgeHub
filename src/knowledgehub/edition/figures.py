"""Gutenberg illustrations → Hub assets (no hotlink). Figures do not block parse."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

ILLUSTRATION_RE = re.compile(r"\[Illustration(?:\s*:\s*(.*?))?\]", re.I | re.S)
IMAGE_NAME = re.compile(r"\.(?:png|jpe?g|gif|svg|webp)\s*$", re.I)


def figures_from_text(text: str, *, src: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for match in ILLUSTRATION_RE.finditer(text or ""):
        caption = (match.group(1) or "").strip() or "Illustration"
        row: dict[str, Any] = {"caption": caption[:500]}
        if src:
            row["src"] = src
        out.append(row)
    return out


def attach_note_figures(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for note in notes:
        body = str(note.get("body") or "")
        figures = figures_from_text(body)
        if figures:
            note["figures"] = figures
    return notes


def ingest_gutenberg_zip_images(
    zip_path: Path,
    dest_dir: Path,
    *,
    prefix: str = "",
) -> list[dict[str, Any]]:
    """Copy image files from a Gutenberg HTML zip into ``corpus/assets/{work}/``."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if info.is_dir() or not IMAGE_NAME.search(name):
                continue
            target_name = f"{prefix}{name}" if prefix else name
            target = dest_dir / target_name
            with zf.open(info) as src, target.open("wb") as dst:
                dst.write(src.read())
            copied.append({"file": target_name, "bytes": info.file_size})
    return copied


def work_asset_dir(corpus: Path, work_id: str) -> Path:
    safe = str(work_id).replace("/", "_")
    return corpus / "assets" / safe
