"""Gutenberg illustrations → Hub assets (no hotlink). Figures do not block parse."""

from __future__ import annotations

import base64
import html as html_lib
import json
import os
import re
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

FIGURE_MARKER_RE = re.compile(r"\[(Illustration|Music)(?:\s*:\s*(.*?))?\]", re.I | re.S)
FIGURE_OPEN_RE = re.compile(r"\[(Illustration|Music)\b", re.I)
IMAGE_NAME = re.compile(r"\.(?:png|jpe?g|gif|svg|webp)\s*$", re.I)
IMG_TAG_RE = re.compile(r"<img\b([^>]*)>", re.I)
ATTR_RE = re.compile(r"""(\w+)\s*=\s*(['"])(.*?)\2""", re.I | re.S)
CAPTION_RE = re.compile(
    r'<div[^>]*\bclass=["\'][^"\']*\bcaption\b[^"\']*["\'][^>]*>(.*?)</div>',
    re.I | re.S,
)
POEM_RE = re.compile(r'<div class="poem">(.*?)</div>', re.I | re.S)
CENTER_RE = re.compile(r'<p[^>]*class=["\']center["\'][^>]*>(.*?)</p>', re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
HTML_MANIFEST = "_html_figures.json"
USER_AGENT = "KnowledgeHub/1.0 (illustration ingest; https://github.com/hiepsikien/KnowledgeHub)"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_HTML_BYTES = 8 * 1024 * 1024


def figures_from_text(text: str, *, src: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for match in FIGURE_MARKER_RE.finditer(text or ""):
        kind = (match.group(1) or "Illustration").strip()
        caption = (match.group(2) or "").strip() or kind
        row: dict[str, Any] = {"caption": caption[:500]}
        if src:
            row["src"] = src
        out.append(row)
    return out


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").casefold()).strip("-")


def _fold(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").casefold()).strip()


def _figure_caption(fig: dict[str, Any]) -> str:
    return _slug(str(fig.get("caption") or fig.get("text") or ""))


def _bind_query(fig: dict[str, Any]) -> str:
    raw = str(fig.get("caption") or fig.get("text") or "")
    raw = FIGURE_MARKER_RE.sub(lambda m: (m.group(2) or "").strip() or (m.group(1) or ""), raw)
    q = _fold(raw)
    stripped = re.sub(r"^(illustration|music)\s*:?\s*", "", q).strip()
    return stripped or q


def _weak_bind_query(query: str) -> bool:
    return not query or query in {"illustration", "music"}


def _strip_tags(raw: str) -> str:
    text = TAG_RE.sub(" ", html_lib.unescape(raw or ""))
    return re.sub(r"\s+", " ", text).strip()


def parse_gutenberg_html_figures(html: str) -> list[dict[str, Any]]:
    """Ordered ``{file, alt, caption}`` from a Gutenberg ``*-h.htm`` page."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in IMG_TAG_RE.finditer(html or ""):
        attrs = {k.lower(): v for k, _, v in ATTR_RE.findall(match.group(1) or "")}
        src = attrs.get("src") or ""
        name = Path(src.replace("\\", "/")).name
        if not name or not IMAGE_NAME.search(name) or name in seen:
            continue
        seen.add(name)
        alt = html_lib.unescape(attrs.get("alt") or "").strip()
        after = _html_after_img(html or "", match.end())
        before = _html_before_img(html or "", match.start())
        cap_match = CAPTION_RE.search(after)
        caption = _strip_tags(cap_match.group(1)) if cap_match else ""
        if not caption:
            poem = POEM_RE.search(after)
            if poem:
                caption = _strip_tags(poem.group(1))
        if not caption:
            centers = CENTER_RE.findall(before)
            if centers:
                caption = _strip_tags(" ".join(centers))
        out.append(
            {
                "file": name,
                "src": src,
                "alt": alt[:500],
                "caption": (caption or alt)[:500],
            }
        )
    return out


def _html_after_img(html: str, end: int) -> str:
    rest = html[end:]
    stop = min(len(rest), 1800)
    lower = rest.lower()
    for token in ("<img", 'class="figcenter"', "class='figcenter'", 'class="inline"', "class='inline'"):
        idx = lower.find(token)
        if idx >= 0:
            stop = min(stop, idx)
    return rest[:stop]


def _html_before_img(html: str, start: int) -> str:
    back = html[max(0, start - 1000) : start]
    lower = back.lower()
    cut = max(
        lower.rfind('class="figcenter"'),
        lower.rfind("class='figcenter'"),
        lower.rfind('class="inline"'),
        lower.rfind("class='inline'"),
    )
    return back[cut:] if cut >= 0 else back[-400:]


def _caption_score(query: str, fig: dict[str, Any]) -> float:
    q = _fold(query)
    if not q or q == "illustration":
        hay = _fold(f"{fig.get('alt') or ''} {fig.get('caption') or ''}")
        if "colophon" in hay:
            return 0.7
        return 0.0
    if q == "music":
        return 0.0
    hay = _fold(f"{fig.get('caption') or ''} {fig.get('alt') or ''}")
    if not hay:
        return 0.0
    if q == hay:
        return 1.0
    alt = _fold(str(fig.get("alt") or ""))
    if alt and q == alt:
        return 0.98
    if q in hay or hay in q:
        q_words, hay_words = q.split(), hay.split()
        # "Bach" must not steal "The House … Bach was born".
        if len(q_words) <= 2 and len(hay_words) > len(q_words) + 3:
            return 0.0
        return 0.94
    qw, hw = set(q.split()), set(hay.split())
    if not qw or not hw:
        return 0.0
    overlap = len(qw & hw) / len(qw)
    if overlap >= 0.55:
        return 0.55 + 0.35 * overlap
    return 0.0


def _set_src(fig: dict[str, Any], filename: str, src_prefix: str) -> None:
    prefix = src_prefix.rstrip("/")
    fig["src"] = f"{prefix}/{filename}" if prefix else filename


def _load_html_manifest(dest_dir: Path) -> list[dict[str, Any]]:
    path = dest_dir / HTML_MANIFEST
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [row for row in data if isinstance(row, dict) and row.get("file")]


def _bind_positional(
    figures: list[dict[str, Any]],
    html_all: list[dict[str, Any]],
    unused_files: dict[str, Path],
    src_prefix: str,
) -> None:
    """Fill leftover figures from leftover HTML images in document order."""
    html_order = [row["file"] for row in html_all]
    file_pos = {name: index for index, name in enumerate(html_order)}
    anchors: list[tuple[int, int]] = [(-1, -1)]
    for index, fig in enumerate(figures):
        name = Path(str(fig.get("src") or "")).name
        if name and name in file_pos:
            anchors.append((index, file_pos[name]))
    anchors.append((len(figures), len(html_order)))
    for left, right in zip(anchors, anchors[1:]):
        fig_lo, html_lo = left
        fig_hi, html_hi = right
        if html_hi < html_lo:
            continue
        run = [i for i in range(fig_lo + 1, fig_hi) if not figures[i].get("src")]
        slots = [html_order[k] for k in range(html_lo + 1, html_hi) if html_order[k] in unused_files]
        if not run or len(run) != len(slots):
            continue
        for fig_i, filename in zip(run, slots):
            unused_files.pop(filename, None)
            _set_src(figures[fig_i], filename, src_prefix)
    leftover_figs = [fig for fig in figures if not fig.get("src")]
    leftover_files = [name for name in html_order if name in unused_files]
    if leftover_figs and leftover_files and all(_weak_bind_query(_bind_query(fig)) for fig in leftover_figs):
        for fig, filename in zip(leftover_figs, leftover_files):
            unused_files.pop(filename, None)
            _set_src(fig, filename, src_prefix)


def bind_figure_src(
    figures: list[dict[str, Any]],
    dest_dir: Path | None,
    *,
    src_prefix: str = "",
) -> list[dict[str, Any]]:
    """Attach ``src`` from ingested files when a figure has only a caption.

    Prefers Gutenberg HTML caption/alt matching (unique score). Falls back to
    unique filename-stem match. Does not download Gutenberg. ``src`` is a Hub
    path (``/assets/{work}/file``).
    """
    if not figures or dest_dir is None or not dest_dir.is_dir():
        return figures
    unused_files = {
        p.name: p
        for p in sorted(dest_dir.iterdir())
        if p.is_file() and IMAGE_NAME.search(p.name)
    }
    unbound = [fig for fig in figures if not fig.get("src")]
    html_all = [row for row in _load_html_manifest(dest_dir) if row["file"] in unused_files]

    for fig in list(unbound):
        query = _bind_query(fig)
        scored: list[tuple[float, dict[str, Any]]] = []
        for html_fig in html_all:
            if html_fig["file"] not in unused_files:
                continue
            score = _caption_score(query, html_fig)
            if score >= 0.55:
                scored.append((score, html_fig))
        if not scored:
            continue
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best = scored[0]
        tied = [row for score, row in scored if abs(score - best_score) < 0.02]
        if len(tied) != 1:
            keys = {_fold(f"{row.get('alt') or ''} {row.get('caption') or ''}") for row in tied}
            if len(keys) != 1:
                continue
            tied_names = {row["file"] for row in tied}
            best = next(row for row in html_all if row["file"] in tied_names and row["file"] in unused_files)
        unused_files.pop(best["file"], None)
        unbound.remove(fig)
        _set_src(fig, best["file"], src_prefix)

    for fig in list(unbound):
        cap = _figure_caption(fig)
        match: Path | None = None
        leftover = list(unused_files.values())
        if cap:
            exact = [p for p in leftover if _slug(p.stem) == cap]
            if len(exact) == 1:
                match = exact[0]
            else:
                contained = [
                    p
                    for p in leftover
                    if (stem := _slug(p.stem)) and (cap in stem or stem in cap)
                ]
                if len(contained) == 1:
                    match = contained[0]
        if match is None:
            continue
        unused_files.pop(match.name, None)
        unbound.remove(fig)
        _set_src(fig, match.name, src_prefix)
    _bind_positional(figures, html_all, unused_files, src_prefix)
    return figures


def bind_body_figure_src(
    blocks: list[dict[str, Any]],
    dest_dir: Path | None,
    *,
    src_prefix: str = "",
) -> list[dict[str, Any]]:
    """Attach ``src`` on ``role: figure`` body blocks (caption = block text)."""
    figs = [b for b in blocks if b.get("role") == "figure" and not b.get("src")]
    if figs:
        bind_figure_src(figs, dest_dir, src_prefix=src_prefix)
    return blocks


def attach_note_figures(
    notes: list[dict[str, Any]],
    *,
    asset_dir: Path | None = None,
    src_prefix: str = "",
) -> list[dict[str, Any]]:
    for note in notes:
        body = str(note.get("body") or "")
        figures = list(note.get("figures") or []) or figures_from_text(body)
        if asset_dir is not None:
            figures = bind_figure_src(figures, asset_dir, src_prefix=src_prefix)
        if figures:
            note["figures"] = figures
    return notes


def work_asset_dir(corpus: Path, work_id: str) -> Path:
    safe = str(work_id).replace("/", "_").replace("\\", "_")
    dest = (corpus / "assets" / safe).resolve()
    root = (corpus / "assets").resolve()
    if dest == root or not dest.is_relative_to(root):
        raise ValueError(f"unsafe work_id: {work_id}")
    return dest


def work_src_prefix(work_id: str) -> str:
    return f"/assets/{str(work_id).replace('/', '_')}"


def normalize_asset_src(work_id: str, src: str, corpus: Path) -> str:
    """Return Hub ``/assets/{work}/{file}`` if the file exists, else ``""`` to clear."""
    raw = str(src or "").strip()
    if not raw:
        return ""
    name = Path(raw.replace("\\", "/")).name
    if not name or not IMAGE_NAME.search(name) or ".." in name:
        raise ValueError(f"invalid asset: {raw}")
    dest = work_asset_dir(corpus, work_id)
    path = dest / name
    if not path.is_file():
        raise ValueError(f"asset not found: {name}")
    return f"{work_src_prefix(work_id)}/{name}"


def list_work_assets(work_id: str, corpus: Path) -> list[dict[str, Any]]:
    """Downloaded images for Final Touch picker (no Gutenberg fetch)."""
    dest = work_asset_dir(corpus, work_id)
    prefix = work_src_prefix(work_id)
    by_name = {row["file"]: row for row in _load_html_manifest(dest)} if dest.is_dir() else {}
    if not dest.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(dest.iterdir()):
        if not path.is_file() or not IMAGE_NAME.search(path.name):
            continue
        meta = by_name.get(path.name) or {}
        out.append(
            {
                "file": path.name,
                "src": f"{prefix}/{path.name}",
                "alt": str(meta.get("alt") or ""),
                "caption": str(meta.get("caption") or ""),
                "bytes": path.stat().st_size,
            }
        )
    return out


def ingest_gutenberg_zip_images(
    zip_path: Path,
    dest_dir: Path,
    *,
    prefix: str = "",
    html_text: str | None = None,
) -> list[dict[str, Any]]:
    """Copy image files from a Gutenberg HTML zip into ``corpus/assets/{work}/``."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    html_from_zip = html_text or ""
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if info.is_dir():
                continue
            if name.lower().endswith((".htm", ".html")) and not html_from_zip:
                with zf.open(info) as src:
                    html_from_zip = src.read().decode("utf-8", errors="replace")
            if not IMAGE_NAME.search(name):
                continue
            target_name = f"{prefix}{name}" if prefix else name
            target = dest_dir / target_name
            with zf.open(info) as src, target.open("wb") as dst:
                dst.write(src.read())
            copied.append({"file": target_name, "bytes": info.file_size})
    if html_from_zip:
        _write_html_manifest(dest_dir, parse_gutenberg_html_figures(html_from_zip))
    return copied


def _write_html_manifest(dest_dir: Path, figures: list[dict[str, Any]]) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / HTML_MANIFEST).write_text(
        json.dumps(figures, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def gutenberg_html_url(gutenberg_id: str) -> str:
    gid = str(gutenberg_id).strip()
    return f"https://www.gutenberg.org/files/{gid}/{gid}-h/{gid}-h.htm"


def gutenberg_image_url(gutenberg_id: str, src: str, *, filename: str = "") -> str:
    """Resolve an HTML ``<img src>`` against the ``*-h.htm`` page URL."""
    rel = (src or "").replace("\\", "/").strip()
    if not rel:
        rel = f"images/{filename}" if filename else ""
    if not rel:
        raise ValueError("missing image src")
    return urljoin(gutenberg_html_url(gutenberg_id), rel)


def _fetch_bytes(url: str, *, timeout: int = 60, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise ValueError(f"response too large ({length} bytes)")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"response too large (>{max_bytes} bytes)")
            chunks.append(chunk)
        return b"".join(chunks)


def _is_image_bytes(raw: bytes) -> bool:
    if not raw or len(raw) < 8:
        return False
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if raw.startswith(b"\xff\xd8\xff"):
        return True
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return True
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return True
    head = raw.lstrip()[:240].lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return True
    return False


def _is_image_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(1024)
    except OSError:
        return False
    return _is_image_bytes(head)


def _wanted_image_files(figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fig in figures:
        name = str(fig.get("file") or "")
        if not name or not IMAGE_NAME.search(name) or name in seen:
            continue
        seen.add(name)
        out.append(fig)
    return out


def ingest_gutenberg_html_images(
    gutenberg_id: str,
    dest_dir: Path,
    *,
    html_text: str | None = None,
    fetch_html: Any = None,
    fetch_image: Any = None,
) -> list[dict[str, Any]]:
    """Download the HTML edition images for a Gutenberg id (no zip required)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    gid = str(gutenberg_id).strip()
    if not gid:
        return []
    html = html_text
    if html is None:
        getter = fetch_html or (
            lambda url: _fetch_bytes(url, max_bytes=MAX_HTML_BYTES).decode("utf-8", errors="replace")
        )
        html = getter(gutenberg_html_url(gid))
    figures = parse_gutenberg_html_figures(html or "")
    wanted = _wanted_image_files(figures)
    copied: list[dict[str, Any]] = []
    errors: list[str] = []
    image_getter = fetch_image or (lambda url: _fetch_bytes(url, max_bytes=MAX_IMAGE_BYTES))
    for fig in wanted:
        name = str(fig.get("file") or "")
        target = dest_dir / name
        if _is_image_file(target):
            copied.append({"file": name, "bytes": target.stat().st_size})
            continue
        try:
            url = gutenberg_image_url(gid, str(fig.get("src") or ""), filename=name)
            raw = image_getter(url)
            if len(raw) > MAX_IMAGE_BYTES:
                raise ValueError(f"{name} too large ({len(raw)} bytes)")
            if not _is_image_bytes(raw):
                raise ValueError(f"{name} is not an image")
            target.write_bytes(raw)
            copied.append({"file": name, "bytes": target.stat().st_size})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
    _write_html_manifest(dest_dir, figures)
    if errors:
        raise RuntimeError("image download incomplete: " + "; ".join(errors))
    return copied


def ensure_work_assets(
    work: dict[str, Any],
    corpus: Path,
    *,
    fetch: bool = False,
    fetch_html: Any = None,
    fetch_image: Any = None,
) -> Path:
    """Return the work asset dir, optionally downloading Gutenberg images."""
    work_id = str(work.get("id") or "")
    dest = work_asset_dir(corpus, work_id)
    if fetch:
        flag = (os.environ.get("KNOWLEDGEHUB_FETCH_IMAGES") or "1").strip().lower()
        if flag in {"0", "false", "no"}:
            fetch = False
    if not fetch:
        return dest
    gid = str(work.get("gutenberg_id") or "").strip()
    if not gid:
        return dest
    ingest_gutenberg_html_images(
        gid,
        dest,
        fetch_html=fetch_html,
        fetch_image=fetch_image,
    )
    return dest


def apply_work_assets(
    work_id: str,
    blocks: list[dict[str, Any]],
    notes: list[dict[str, Any]] | None = None,
    *,
    corpus: Path,
    work: dict[str, Any] | None = None,
    fetch: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bind local asset ``src`` onto figure blocks and note figures."""
    notes = list(notes or [])
    if not work_id:
        return blocks, notes
    row = work if work is not None else {"id": work_id}
    dest = ensure_work_assets(row, corpus, fetch=fetch)
    prefix = work_src_prefix(work_id)
    bind_body_figure_src(blocks, dest if dest.is_dir() else None, src_prefix=prefix)
    attach_note_figures(notes, asset_dir=dest if dest.is_dir() else None, src_prefix=prefix)
    return blocks, notes


def edition_has_unbound_figures(edition: dict[str, Any]) -> bool:
    """True when a figure block or note figure still lacks ``src``."""

    def unbound_block(block: dict[str, Any]) -> bool:
        return block.get("role") == "figure" and not str(block.get("src") or "").strip()

    def unbound_notes(notes: list[Any] | None) -> bool:
        for note in notes or []:
            if not isinstance(note, dict):
                continue
            for fig in note.get("figures") or []:
                if isinstance(fig, dict) and not str(fig.get("src") or "").strip():
                    return True
        return False

    if any(unbound_block(b) for b in edition.get("blocks") or [] if isinstance(b, dict)):
        return True
    if unbound_notes(edition.get("notes")):
        return True
    for chapter in edition.get("_chapters") or []:
        if not isinstance(chapter, dict):
            continue
        if any(unbound_block(b) for b in chapter.get("blocks") or [] if isinstance(b, dict)):
            return True
        if unbound_notes(chapter.get("notes")):
            return True
    return False


def bind_edition_assets(
    edition: dict[str, Any],
    work: dict[str, Any],
    corpus: Path,
    *,
    fetch: bool = False,
) -> dict[str, Any]:
    """Bind figure ``src`` on a packaged edition (publish / preview)."""
    work_id = str(work.get("id") or "")
    ensure_work_assets(work, corpus, fetch=fetch)
    apply_work_assets(
        work_id,
        list(edition.get("blocks") or []),
        list(edition.get("notes") or []),
        corpus=corpus,
        work=work,
        fetch=False,
    )
    for chapter in edition.get("_chapters") or []:
        apply_work_assets(
            work_id,
            list(chapter.get("blocks") or []),
            list(chapter.get("notes") or []),
            corpus=corpus,
            work=work,
            fetch=False,
        )
    return edition


def collect_publish_assets(
    blocks: list[dict[str, Any]],
    notes: list[dict[str, Any]] | None,
    dest_dir: Path,
) -> list[dict[str, Any]]:
    """Base64 payloads Read can store under ``/api/books/{id}/media/``."""
    names: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        src = str(block.get("src") or "")
        name = Path(src).name
        if name and name not in seen and IMAGE_NAME.search(name):
            seen.add(name)
            names.append(name)
    for note in notes or []:
        for fig in note.get("figures") or []:
            if not isinstance(fig, dict):
                continue
            name = Path(str(fig.get("src") or "")).name
            if name and name not in seen and IMAGE_NAME.search(name):
                seen.add(name)
                names.append(name)
    out: list[dict[str, Any]] = []
    for name in names:
        path = dest_dir / name
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")
        out.append(
            {
                "filename": name,
                "content_type": mime,
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
            }
        )
    return out
