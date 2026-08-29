from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .catalog import get_work, is_hub_translation, resolve_content_path, update_read_publication, work_credits
from .edition.footnotes import glossary_from_annotations, glossary_from_footnotes, notes_from_annotations
from .edition.ref import build_read_edition
from .edition.ref_schema import validate_edition
from .normalize import normalize_manuscript
from .read_edition_service import edition_for_publish
from .paths import corpus_root
from .read_options import validate_category_slug, validate_split_length
from .translation.assemble import IncompleteTranslation, assemble_finals, chapter_finals
from .translation.paths import annotations_file


class PublishError(RuntimeError):
    pass


def _work_for_normalize(work: dict[str, Any], corpus: Path) -> dict[str, Any]:
    enriched = dict(work)
    enriched["_corpus_root"] = str(corpus)
    return enriched


def _attach_edition(payload: dict[str, Any], report: dict[str, Any]) -> None:
    edition = report.get("edition") or {}
    if not edition.get("edition_format"):
        return
    payload["edition_format"] = edition["edition_format"]
    payload["edition_hash"] = edition.get("edition_hash")
    payload["content_kind"] = edition.get("content_kind")
    payload["reading_markdown"] = edition.get("reading_markdown")
    payload["blocks"] = edition.get("blocks")
    payload["split_hints"] = edition.get("split_hints")
    if edition.get("quotation_profile"):
        payload["quotation_profile"] = edition["quotation_profile"]
    if edition.get("reading_markdown"):
        payload["raw_text"] = edition["reading_markdown"]


def _payload(work: dict[str, Any], text: str, *, corpus: Path | None = None) -> dict[str, Any]:
    read = work.get("read") or {}
    rights = work.get("rights") or {}
    credits = work_credits(work, corpus=corpus)
    return {
        "hub_work_id": work["id"],
        "hub_version": int(work.get("version") or 1),
        "hub_content_hash": work.get("content_hash"),
        "title": work["title"],
        "description": work.get("description") or work["title"],
        "language": work.get("language") or "en",
        "license": work.get("license"),
        "source_url": work.get("source_url") or "",
        "category_slug": read.get("category_slug") or "essays",
        "price_cents": int(read.get("price_cents") or 0),
        "split_length": read.get("split_length") or "standard",
        "status": "pending_review",
        "hub_license_snapshot": {
            "license": work.get("license"),
            "license_source": work.get("license_source"),
            "rights": rights,
        },
        "raw_text": text,
        "credits": credits,
    }


def prepare_publish(
    work_id: str,
    *,
    corpus: Path | None = None,
    title: str | None = None,
    description: str | None = None,
    category_slug: str | None = None,
    price_cents: int | None = None,
    split_length: str | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    if persist:
        try:
            update_read_publication(
                work_id,
                title=title,
                description=description,
                category_slug=category_slug,
                price_cents=price_cents,
                split_length=split_length,
                corpus=root,
            )
        except ValueError as exc:
            raise PublishError(str(exc)) from exc
    work = get_work(work_id, corpus=root)
    consumers = ((work.get("rights") or {}).get("consumers") or {})
    if consumers.get("read") != "allowed":
        raise PublishError(
            f"{work_id} is not allowed for Read (rights.consumers.read != allowed)"
        )
    if is_hub_translation(work):
        return _prepare_translation_publish(
            work,
            root=root,
            title=title,
            description=description,
            category_slug=category_slug,
            price_cents=price_cents,
            split_length=split_length,
        )
    path = resolve_content_path(work, root=root)
    if not path.is_file():
        raise PublishError(f"missing manuscript: {path}")
    if not work.get("content_hash"):
        raise PublishError(f"{work_id} has no content_hash — run: knowledgehub hash")
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        text, report = normalize_manuscript(
            raw,
            language=str(work.get("language") or "en"),
            work=_work_for_normalize(work, root),
            use_llm=False,
        )
    except ValueError as exc:
        raise PublishError(str(exc)) from exc
    reading_text, footnote_glossary = glossary_from_footnotes(text)
    if not footnote_glossary:
        _, footnote_glossary = glossary_from_footnotes(raw)
    try:
        edition, package_meta = edition_for_publish(work_id, corpus=root)
        reading_text = str(edition.get("reading_markdown") or reading_text)
        report = dict(report)
        report["edition"] = edition
        report["read_edition"] = package_meta
        validate_errors = validate_edition(edition)
        if validate_errors:
            raise PublishError(f"REF validation: {'; '.join(validate_errors[:3])}")
    except ValueError as exc:
        raise PublishError(str(exc)) from exc
    payload = _payload(work, reading_text, corpus=root)
    _attach_edition(payload, report)
    if footnote_glossary:
        payload["glossary"] = footnote_glossary
    report = dict(report)
    report["glossary_count"] = len(footnote_glossary)
    report["stripped_footnotes"] = reading_text != text
    _apply_publish_overrides(
        payload,
        title=title,
        description=description,
        category_slug=category_slug,
        price_cents=price_cents,
        split_length=split_length,
    )
    payload["_normalize"] = report
    return payload


def _prepare_translation_publish(
    work: dict[str, Any],
    *,
    root: Path,
    title: str | None,
    description: str | None,
    category_slug: str | None,
    price_cents: int | None,
    split_length: str | None,
) -> dict[str, Any]:
    source_id = str(work.get("derived_from") or "")
    try:
        text, meta = assemble_finals(source_id, require_complete=True)
    except IncompleteTranslation as exc:
        raise PublishError(str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise PublishError(str(exc)) from exc
    try:
        edition, package_meta = edition_for_publish(str(work.get("id") or ""), corpus=root)
        ref_report = package_meta.get("report") or {}
    except ValueError:
        edition, ref_report = build_read_edition(
            text,
            family="plain",
            language=str(work.get("language") or "vi"),
            work_id=str(work.get("id") or ""),
        )
        package_meta = {}
    text = str(edition.get("reading_markdown") or text)
    validate_errors = validate_edition(edition)
    if validate_errors:
        raise PublishError(f"REF validation: {'; '.join(validate_errors[:3])}")
    payload = _payload(work, text, corpus=root)
    _attach_edition(payload, {"edition": edition, "ref": ref_report, "read_edition": package_meta})
    payload["hub_content_hash"] = meta["content_hash"]
    payload["language"] = work.get("language") or "vi"
    glossary: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    ann_path = annotations_file(source_id)
    if ann_path.is_file():
        try:
            store = json.loads(ann_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            store = {}
        raw_anns = list(store.get("annotations") or [])
        chapter_texts = chapter_finals(source_id)
        notes = notes_from_annotations(raw_anns, chapter_texts=chapter_texts)
        glossary = glossary_from_annotations(raw_anns, chapter_texts=chapter_texts)
    if notes:
        payload["notes"] = [
            {
                "id": row.get("id") or "",
                "kind": row.get("kind") or "footnote",
                "label": row.get("label") or "",
                "marker": row.get("marker") or "",
                "anchor": row.get("anchor") or "",
                "chapter": row.get("chapter") or "",
                "body": row.get("body") or "",
                "group_label": row.get("group_label") or "Chú thích",
            }
            for row in notes
        ]
    if glossary:
        payload["glossary"] = glossary
    _apply_publish_overrides(
        payload,
        title=title,
        description=description,
        category_slug=category_slug,
        price_cents=price_cents,
        split_length=split_length,
    )
    payload["_normalize"] = {
        "origin": "hub_translation",
        "source_work_id": source_id,
        "chapters": meta["chapters"],
        "assembled_chars": meta["chars"],
        "glossary_count": len(glossary),
        "stripped_footnotes": False,
    }
    return payload


def _apply_publish_overrides(
    payload: dict[str, Any],
    *,
    title: str | None,
    description: str | None,
    category_slug: str | None,
    price_cents: int | None,
    split_length: str | None,
) -> None:
    if title and title.strip():
        payload["title"] = title.strip()
    if description is not None:
        payload["description"] = description.strip() or payload["title"]
    if category_slug is not None:
        try:
            payload["category_slug"] = validate_category_slug(category_slug)
        except ValueError as exc:
            raise PublishError(str(exc)) from exc
    if price_cents is not None:
        payload["price_cents"] = max(0, int(price_cents))
    if split_length is not None:
        try:
            payload["split_length"] = validate_split_length(split_length)
        except ValueError as exc:
            raise PublishError(str(exc)) from exc


def preview_normalized(
    work_id: str,
    *,
    corpus: Path | None = None,
    full: bool = False,
    head_chars: int = 12000,
    tail_chars: int = 2500,
) -> dict[str, Any]:
    root = corpus or corpus_root()
    work = get_work(work_id, corpus=root)
    if is_hub_translation(work):
        source_id = str(work.get("derived_from") or "")
        try:
            text, meta = assemble_finals(source_id, require_complete=True)
        except IncompleteTranslation as exc:
            raise PublishError(str(exc)) from exc
        except (FileNotFoundError, ValueError) as exc:
            raise PublishError(str(exc)) from exc
        truncated = (not full) and len(text) > head_chars + tail_chars
        out: dict[str, Any] = {
            "id": work["id"],
            "title": work.get("title"),
            "normalize": {
                "origin": "hub_translation",
                "source_work_id": source_id,
                "chapters": meta["chapters"],
                "assembled_chars": meta["chars"],
            },
            "truncated": truncated,
        }
        if truncated:
            out["head"] = text[:head_chars]
            out["tail"] = text[-tail_chars:]
        else:
            out["text"] = text
        return out
    path = resolve_content_path(work, root=root)
    if not path.is_file():
        raise PublishError(f"missing manuscript: {path}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        text, report = normalize_manuscript(
            raw,
            language=str(work.get("language") or "en"),
            work=_work_for_normalize(work, root),
        )
    except ValueError as exc:
        raise PublishError(str(exc)) from exc
    truncated = (not full) and len(text) > head_chars + tail_chars
    out = {
        "id": work["id"],
        "title": work.get("title"),
        "normalize": report,
        "truncated": truncated,
    }
    if truncated:
        out["head"] = text[:head_chars]
        out["tail"] = text[-tail_chars:]
    else:
        out["text"] = text
    return out


def _read_body(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if not k.startswith("_")}


def publish_to_read(
    work_id: str,
    *,
    corpus: Path | None = None,
    api_url: str | None = None,
    token: str | None = None,
    dry_run: bool = True,
    title: str | None = None,
    description: str | None = None,
    category_slug: str | None = None,
    price_cents: int | None = None,
    split_length: str | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    payload = prepare_publish(
        work_id,
        corpus=corpus,
        title=title,
        description=description,
        category_slug=category_slug,
        price_cents=price_cents,
        split_length=split_length,
        persist=persist,
    )
    report = payload.get("_normalize") or {}
    body = _read_body(payload)
    if dry_run:
        preview = dict(body)
        preview["raw_text"] = f"<{len(body['raw_text'])} chars>"
        glossary = body.get("glossary") or []
        notes = body.get("notes") or []
        preview["glossary"] = [
            {
                "name": row.get("name"),
                "aliases": row.get("aliases") or [],
                "group_label": row.get("group_label"),
                "summary_chars": len(str(row.get("summary") or "")),
            }
            for row in glossary
        ]
        preview["glossary_count"] = len(glossary)
        preview["notes_count"] = len(notes)
        return {"dry_run": True, "normalize": report, "payload": preview}

    base = (api_url or os.environ.get("READ_API_URL") or "http://127.0.0.1:8000").rstrip("/")
    secret = token or os.environ.get("READ_HUB_TOKEN") or ""
    if not secret:
        raise PublishError("Set READ_HUB_TOKEN (same value as Read HUB_SYNC_TOKEN)")

    req = urllib.request.Request(
        f"{base}/api/internal/hub/works",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Hub-Sync-Token": secret,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PublishError(f"Read {exc.code}: {detail}") from exc
