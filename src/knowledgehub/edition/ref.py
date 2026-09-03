from __future__ import annotations

from typing import Any

from .block_ids import assign_block_ids, mark_chapter_banner
from .footnotes import attach_footnote_bodies, attach_note_hosts
from .figures import attach_note_figures, work_asset_dir
from .inline_spans import annotate_blocks
from .label_rules import label_lines_rules
from .lines import iter_lines, normalize_wiki_source
from .llm_blocks import relabel_uncertain_segments
from .llm_defaults import default_use_llm_relabel, ref_llm_model
from .merge_blocks import labels_to_blocks
from .reflow import unwrap_hard_wrap
from .serialize import build_edition_document, grotius_latin_to_blockquote
from .structure import group_dramatis_blocks, group_stanzas, merge_adjacent_blockquotes, merge_adjacent_headings, merge_adjacent_metadata
from .work_rules import apply_work_rules

CJK_LANG = {"ja", "zh", "ko"}


def apply_wrap_overrides(labels: list[Any], overrides: dict[int, bool]) -> None:
    for index, join in overrides.items():
        if 0 <= index < len(labels):
            labels[index].join_next = join


def normalize_edition_source(
    text: str,
    *,
    family: str = "plain",
    language: str = "en",
) -> tuple[str, list[str], bool]:
    """Same source transform parse uses before labeling (wiki / unwrap)."""
    lang = (language or "en").lower()[:2]
    apparatus: list[str] = []
    body = text
    unwrapped = False
    if family == "plain":
        body, wiki_apparatus = normalize_wiki_source(text)
        apparatus.extend(wiki_apparatus)
    elif family in {"scholastic", "archive_scan"} and lang not in CJK_LANG:
        body, unwrapped = unwrap_hard_wrap(text, family=family, language=lang)
    if lang in CJK_LANG:
        body, unwrapped = unwrap_hard_wrap(body, family=family, language=lang)
    return body, apparatus, unwrapped


def label_edition_lines(
    body: str,
    *,
    family: str,
    language: str = "en",
    use_llm: bool = False,
    wrap_overrides: dict[int, bool] | None = None,
) -> tuple[list[Any], list[Any], list[Any]]:
    lang = (language or "en").lower()[:2]
    lines = iter_lines(body)
    labels = label_lines_rules(lines, family=family, source_text=body)
    llm_events: list[Any] = []
    if use_llm and lang not in CJK_LANG:
        labels, llm_events = relabel_uncertain_segments(
            lines, labels, enabled=True, model=ref_llm_model()
        )
    if wrap_overrides:
        apply_wrap_overrides(labels, wrap_overrides)
    return lines, labels, llm_events


def blocks_from_labels(
    lines: list[Any],
    labels: list[Any],
    *,
    work_id: str | None = None,
    language: str = "en",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """labels_to_blocks plus the grouping parse applies before annotate."""
    lang = (language or "en").lower()[:2]
    blocks = labels_to_blocks(lines, labels)
    if lang in CJK_LANG:
        return annotate_blocks(blocks)
    if work_id and work_id.startswith("grotius--"):
        blocks = grotius_latin_to_blockquote(blocks)
    blocks = merge_adjacent_headings(blocks)
    blocks = merge_adjacent_metadata(blocks)
    blocks = merge_adjacent_blockquotes(blocks)
    blocks = group_dramatis_blocks(blocks)
    blocks = group_stanzas(blocks)
    return annotate_blocks(blocks)


def stamp_edition_blocks(
    blocks: list[dict[str, Any]],
    notes: list[dict[str, Any]] | None = None,
    *,
    work_id: str | None = None,
    family: str = "plain",
    chapter_id: str | None = None,
    chapter_title: str | None = None,
    apply_matchers: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Matchers → stable block_id → chapter-banner flag → note hosts."""
    if apply_matchers:
        blocks = apply_work_rules(blocks, work_id=work_id, family=family)
    blocks = assign_block_ids(blocks, chapter_id=chapter_id or "book")
    blocks = mark_chapter_banner(blocks, chapter_title)
    notes = attach_note_hosts(list(notes or []), blocks)
    asset_dir = None
    src_prefix = ""
    if work_id:
        from ..paths import corpus_root

        asset_dir = work_asset_dir(corpus_root(), work_id)
        src_prefix = f"/assets/{str(work_id).replace('/', '_')}"
    notes = attach_note_figures(notes, asset_dir=asset_dir, src_prefix=src_prefix)
    return blocks, notes


def build_read_edition(
    text: str,
    *,
    family: str = "plain",
    language: str = "en",
    use_llm: bool | None = None,
    work_id: str | None = None,
    wrap_overrides: dict[int, bool] | None = None,
    chapter_id: str | None = None,
    chapter_title: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Structured REF/1 edition from stripped manuscript text."""
    llm_enabled = default_use_llm_relabel() if use_llm is None else use_llm
    lang = (language or "en").lower()[:2]
    body, apparatus, unwrapped = normalize_edition_source(text, family=family, language=language)
    cjk = lang in CJK_LANG
    lines, labels, llm_events = label_edition_lines(
        body,
        family=family,
        language=language,
        use_llm=llm_enabled and not cjk,
        wrap_overrides=wrap_overrides,
    )
    blocks, quotation_profile = blocks_from_labels(lines, labels, work_id=work_id, language=language)
    blocks, notes = attach_footnote_bodies(blocks, body)
    blocks, notes = stamp_edition_blocks(
        blocks,
        notes,
        work_id=work_id,
        family=family,
        chapter_id=chapter_id,
        chapter_title=chapter_title,
    )
    joined = any(label.join_next for label in labels) or unwrapped
    edition = build_edition_document(
        blocks,
        language=language,
        source_family=family,
        quotation_profile=quotation_profile,
        apparatus_dropped=apparatus or None,
    )
    if notes:
        edition["notes"] = notes
    return edition, {
        "ref_mode": "rule_fallback" if cjk else ("llm_hybrid" if llm_enabled else "rule"),
        "line_count": len(lines),
        "block_count": len(blocks),
        "llm_segments": llm_events,
        "unwrapped": joined if not cjk else unwrapped,
        "quotation_profile": quotation_profile,
        "apparatus_dropped": apparatus,
        "notes_linked": len(notes),
    }
