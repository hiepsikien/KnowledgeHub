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


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").casefold()).strip("-")


def bind_figure_src(
    figures: list[dict[str, Any]],
    dest_dir: Path | None,
    *,
    src_prefix: str = "",
) -> list[dict[str, Any]]:
    """Attach ``src`` from ingested files when a figure has only a caption.

    Does not download Gutenberg. ``src`` is a Hub path (``/assets/{work}/file``);
    serving that route is still Read/Hub lockstep.
    """
    if not figures or dest_dir is None or not dest_dir.is_dir():
        return figures
    unused = [p for p in sorted(dest_dir.iterdir()) if p.is_file() and IMAGE_NAME.search(p.name)]
    unbound = [fig for fig in figures if not fig.get("src")]
    for fig in unbound:
        cap = _slug(str(fig.get("caption") or ""))
        match: Path | None = None
        for path in unused:
            stem = _slug(path.stem)
            if cap and stem and (cap in stem or stem in cap):
                match = path
                break
        if match is None and len(unbound) == 1 and len(unused) == 1:
            match = unused[0]
        if match is None:
            continue
        unused.remove(match)
        prefix = src_prefix.rstrip("/")
        fig["src"] = f"{prefix}/{match.name}" if prefix else match.name
    return figures


def attach_note_figures(
    notes: list[dict[str, Any]],
    *,
    asset_dir: Path | None = None,
    src_prefix: str = "",
) -> list[dict[str, Any]]:
    for note in notes:
        body = str(note.get("body") or "")
        figures = figures_from_text(body)
        if asset_dir is not None:
            figures = bind_figure_src(figures, asset_dir, src_prefix=src_prefix)
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
